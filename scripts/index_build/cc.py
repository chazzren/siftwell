"""Common Crawl URL index: every captured URL under a SURT prefix (e.g. "io,greenhouse,boards)/").

The public CDX API (index.commoncrawl.org) is often overloaded (504 after 10 s), so this reads the index files
themselves from data.commoncrawl.org: a binary search over the crawl's cluster.idx with HTTP Range requests finds the
compressed index blocks that hold the prefix, then each block (~250 KB gzip, ~3,000 URLs) is fetched by range and
unpacked. No key, no account; the files are public (https://commoncrawl.org/terms-of-use)."""
import gzip, json, re

from . import net

DATA = "https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/{file}"
COLLINFO = "https://index.commoncrawl.org/collinfo.json"
WINDOW = 65536


def latest_crawls(n=2):
    """The newest n crawl ids, like CC-MAIN-2026-43."""
    try:
        d = net.get_json(COLLINFO, robots=False, tries=3, timeout=30)
        return [c["id"] for c in d if re.fullmatch(r"CC-MAIN-\d{4}-\d{2}", c.get("id", ""))][:n]
    except Exception:
        return []


class Index:
    def __init__(self, crawl):
        self.crawl = crawl
        self.url = DATA.format(crawl=crawl, file="cluster.idx")
        self.size = None

    def _range(self, a, b):
        return net.get(self.url, rng=(a, b), robots=False, timeout=60)

    def _size(self):
        if self.size is None:
            import urllib.request
            req = urllib.request.Request(self.url, method="HEAD", headers={"User-Agent": net.user_agent()})
            with net.netsafe.urlopen(req, timeout=30) as r:
                self.size = int(r.headers["Content-Length"])
        return self.size

    def _line_after(self, pos):
        """(key, byte offset of the line) of the first whole line starting after pos."""
        chunk = self._range(pos, min(pos + 4096, self._size() - 1))
        if pos > 0:
            i = chunk.find(b"\n")
            if i < 0:
                return None, None
            start = i + 1
        else:
            start = 0
        j = chunk.find(b"\n", start)
        line = chunk[start:j if j >= 0 else None]
        return line.split(b" ", 1)[0].decode("utf-8", "replace"), pos + start

    def blocks(self, prefix, cap=400):
        """[(cdx file, offset, length)] for the index blocks that can hold keys starting with prefix."""
        lo, hi = 0, self._size()
        while hi - lo > WINDOW:              # find a position whose next line's key is < prefix, close to the prefix
            mid = (lo + hi) // 2
            key, _ = self._line_after(mid)
            if key is None or key >= prefix:
                hi = mid
            else:
                lo = mid
        out, prev, pos, done = [], None, lo, False
        while not done and pos < self._size():
            chunk = self._range(pos, min(pos + WINDOW, self._size() - 1))
            lines = chunk.split(b"\n")
            if pos + len(chunk) < self._size():
                keep = lines.pop()               # (partial last line: read again in the next window)
                nxt = pos + len(chunk) - len(keep)
            else:
                nxt = self._size()
            if pos > 0 and pos == lo:
                lines = lines[1:]                # (partial first line)
            for ln in lines:
                parts = ln.decode("utf-8", "replace").split("\t")
                if len(parts) < 4:
                    continue
                key = parts[0].split(" ", 1)[0]
                blk = (parts[1], int(parts[2]), int(parts[3]))
                if key < prefix:
                    prev = blk                   # this block starts before the prefix and may run into it
                    continue
                if not key.startswith(prefix):
                    if prev:
                        out.append(prev)
                    done = True
                    break
                if prev:
                    out.append(prev)
                prev = blk
                if len(out) >= cap:
                    done = True
                    break
            pos = nxt
        return list(dict.fromkeys(out))[:cap]

    def urls(self, prefix, cap=400, log=print):
        """Every URL captured under prefix (duplicates included; callers dedupe by tenant)."""
        blocks = self.blocks(prefix, cap)
        log(f"  cc {self.crawl} {prefix}: {len(blocks)} index blocks")
        for f, off, ln in blocks:
            try:
                raw = net.get(DATA.format(crawl=self.crawl, file=f"{f}"), rng=(off, off + ln - 1), robots=False, timeout=90)
                text = gzip.decompress(raw).decode("utf-8", "replace")
            except Exception as e:
                log(f"  cc block {f}@{off} failed: {type(e).__name__}")
                continue
            for line in text.splitlines():
                if not line.startswith(prefix):
                    continue
                i = line.find("{")
                if i < 0:
                    continue
                try:
                    d = json.loads(line[i:])
                except ValueError:
                    continue
                if str(d.get("status", "200"))[:1] in ("2", "3"):
                    yield d.get("url", "")
