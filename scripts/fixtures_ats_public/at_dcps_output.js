

var addthis_config = {
          services_compact: 'email, facebook, twitter, more',
          services_exclude: 'print'
}

var VacanciesAreOnThisPage = true

//window.onerror = function nada(){}

function centerWin(zwidth,zheight){
       var winHeight
       var winWidth
       winHeight = screen.availHeight
       winWidth = screen.width
       if (zwidth > winWidth){zwidth=winWidth}
       if (zheight > winHeight){zheight=winHeight}
       zleft = parseInt((winWidth/2)-(zwidth/2))
       if (zleft < 10){zleft = 0}
       ztop = parseInt((winHeight/2)-(zheight/2))
       if (ztop < 25){ztop = 0}
       var x = "width=" + zwidth + ",height=" + zheight + ",left=" + zleft + ",top=" + ztop
       return x
}

function applyFor(posJobCode,posFirstChoice,posSpecialty){
       var openwindow = false
       if (document.layers){
              alert("Please go back and then click 'Start an Application' to apply for this position.")
              return false;
       }
       var OpenWin = true
       try {
              if (typeof self.opener.updateApp == "boolean"){
                     OpenWin = false
              }
       } catch (e) {
              OpenWin = true
       }

       if (OpenWin){
              var applyFor = window.open("https://www.applitrack.com/dcps/onlineapp/_application.aspx?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
              applyFor.focus()
       } else {
              window.opener.location = "javascript: applyFor('" + posJobCode + "','" + posFirstChoice + "','" + posSpecialty + "')"
              self.close()
       }
}

function oldWay(){
       var openwindow = false
       if (document.layers){
              alert("Please go back and then click 'Start an Application' to apply for this position.")
              return false;
       }
       if (opener == null){
              var applyFor = window.open("https://www.applitrack.com/dcps/onlineapp/_application.aspx?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
              applyFor.focus()
       }else{
              if (typeof self.opener == "undefined"){
                     var applyFor = window.open("https://www.applitrack.com/dcps/onlineapp/_application.aspx?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
                     applyFor.focus()
              }else{
                     if (typeof self.opener.updateApp == "boolean"){
                           window.opener.location = "javascript: applyFor('" + posJobCode + "','" + posFirstChoice + "','" + posSpecialty + "')"
                           self.close()
                     }else{
                           var applyFor = window.open("https://www.applitrack.com/dcps/onlineapp/_application.aspx?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
                           applyFor.focus()
                     }
              }
       }
}
function applyForInternal(posJobCode,posFirstChoice,posSpecialty){
    var passDistrictCode;

       var applyFor = window.open("https://www.applitrack.com/dcps/onlineapp/_application.aspx?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + passDistrictCode + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
       applyFor.focus()
}

function applyForOutsideDistrict(district,posJobCode,posFirstChoice,posSpecialty){
    var applyPage;
    var applyWinSize;
    
        applyPage = '_application.aspx';
    
       var applyFor = window.open("https://www.applitrack.com/" + district + "/onlineapp/" + applyPage + "?posJobCodes=" + posJobCode + "&posFirstChoice=" + posFirstChoice + "&posSpecialty=" + posSpecialty + "","applyFor","location=no,resizable=yes,scrollbars=yes," + centerWin(795,550))
       applyFor.focus()
}

function toggle_block(i) {
       if (AppliTrack_$(i).style.display == 'none'){ AppliTrack_$(i).style.display = 'block';} else {AppliTrack_$(i).style.display = 'none';}
       setUpPageBreaks()
       return false;
}

function submitAppliTrackSearch(){
       AppliTrack_SearchExecute(null);
}

/* Deprecated; use AppliTrack_SearchExecute() */
function AppliTrackSort(key){
       winLoc = window.location.toString()
       if (window.location.search == "") {
              window.location = winLoc + "?AppliTrackSort=" + escape(key)
       }else{
              if (window.location.search.indexOf("AppliTrackSort=") > 0){
                     var currLoc = winLoc.substring(0,winLoc.indexOf("AppliTrackSort="))
                     window.location = winLoc.replace(/([^a-zA-Z0-9\-\.]+AppliTrackSort=)([a-zA-Z0-9\-\.]+)([&a-zA-Z0-9\-\.]*)/i,'$1' + escape(key) + '$3');
              }else{
                     window.location = winLoc + (winLoc.indexOf("?") < 0?"?":"&") + "AppliTrackSort=" + escape(key)
              }
       }
}

function AppliTrackSearchFocus(){
    var e = AppliTrack_$('AppliTrackPostingSearchBasic');
       if (e && e.value == "Search Postings"){
              e.value = ""
              e.style.color = "black"
              e.style.fontStyle = "normal"
       }
}
function AppliTrackSearchBlur(){
    var e = AppliTrack_$('AppliTrackPostingSearchBasic');
       if (e && e.value == ""){
              e.value = "Search Postings"
              e.style.color = "#999999"
              e.style.fontStyle = "italic"
       }
}
function AppliTrack_WatchForEnter(e){
       if(window.event)
        key = window.event.keyCode;     //IE
    else
        key = e.which;     //firefox

    if (key == 13)
    {
              AppliTrack_SearchExecute(null);

              if(window.event){
                  window.event.cancelBubble = true;
                  window.event.returnValue = false;
              }

              if (event && event.stopPropagation) {
            event.stopPropagation();
        }
        if (event && event.preventDefault) {
            event.preventDefault();
        }
        return false;
    }
}

function AppliTrackInit(){
       try{
           var sf = AppliTrack_$('AppliTrackPostingSearchBasic');
           var sc = AppliTrack_$('AppliTrackSearchSubCategory');
           if(sf){sf.value = "Search Postings"}
           if(sc){sc.disabled = true;}
           if (window.location.search.indexOf("category") > 0 || window.location.search.indexOf("AppliTrackPostingSearchBasic") > 0){
                  AppliTrack_$('AppliTrackPostings').scrollIntoView(true)
           }
       }
    catch(e){}
}
setTimeout('AppliTrackInit()',100)
function AppliTrack_ToggleAdvancedSearch(){
    var hc = AppliTrack_$('AppliTrackSearchAdvancedHeaderCollapsed');
    var he=AppliTrack_$('AppliTrackSearchAdvancedHeaderExpanded');
    var c=AppliTrack_$('AppliTrackSearchAdvancedContainer');
    var s=AppliTrack_$('AppliTrackSearchSimpleContainer');
    if(!hc||!he||!c) return;
    if(hc.style.display=='block'){
        hc.style.display='none';
        he.style.display='block';
        c.style.display='block';
        s.style.opacity='.5';
        s.style.filter='alpha(opacity=50)';
    }
    else{
        hc.style.display='block';
        he.style.display='none';
        c.style.display='none';
        s.style.opacity='1';
        s.style.filter='alpha(opacity=100)';
    }
}

function AppliTrack_onKeyPressToggle(e){
    if(window.event) {
        key = window.event.keyCode;     //IE
    } else {
        key = e.which;     //firefox
    }
    //toggle advanced settings on 'enter' and 'space' keypress
    if (key == 13 || key == 32) {
        AppliTrack_ToggleAdvancedSearch();
    }
}

function AppliTrack_SearchCategorySelect(){
    var c = AppliTrack_$('AppliTrackSearchCategory');
    var sc=AppliTrack_$('AppliTrackSearchSubCategory');
    if(!c||!sc){return;}
    if(c.options&&c.selectedIndex > 0){
        sc.disabled=false;
        var v = c.options[c.selectedIndex].value;
        if(v!=''){
            try{
                eval('var g = '+v);
                sc.options.length = 0;
                sc.options[sc.options.length] = new Option('All ' + g.id + ' postings','');

                for(var i=0;i < g.vals.length;i++){
                    if(g.vals[i]==''){
                        sc.options[sc.options.length] = new Option('All ' + g.id + ' postings','');
                    }
                    else{
                        sc.options[sc.options.length] = new Option(g.vals[i],g.vals[i]);
                    }
                }
            }catch(e){/*malformed option*/}
        }
    }
    else{
        sc.options.length = 0;
        sc.disabled = true;
    }

}

function AppliTrack_RadiusSelect(){
    var l = AppliTrack_$('AppliTrackSearchLocation');
    var sr=AppliTrack_$('AppliTrackSearchRadius');
    var zct=AppliTrack_$('AppliTrackZipCode');
    var zcv = AppliTrack_$('AppliTrackZipValidator');
     if(!l||!sr){return;}
      if(l.options[l.selectedIndex].value != ''){
        sr.disabled = true;
        zct.disabled = true;
        zcv.style.visibility='hidden';
        }
        else
        {
          sr.disabled = false;
          zct.disabled = false;
        }
}


function AppliTrack_SearchExecute(f /*,execute search, default advanced form visible*/){

  var ll = AppliTrack_$('AppliTrackSearchLocation');
  var zct = AppliTrack_$('AppliTrackZipCode');
  var zcv = AppliTrack_$('AppliTrackZipValidator');
  var sbb = AppliTrack_$('AppliTrackPostingSearchBasic');
  var validateZip =true;
  if (zct !=null) {
    if (zct.value != '' ){
        validateZip =  /(^\d{5}$)|(^\d{5}-\d{4}$)/.test(zct.value);
    }
    else
    {
        validateZip = true;
    }
  }
  else
  {
    validateZip = true;
  }

  if(( sbb.value !='Search Postings') || validateZip ){
    var loc = window.location.search;
       if(loc.substring(0,1) == '?'){
        //always replace the current search - refactor this to eliminate compounding searching
           loc = 'all=1';
        //loc= loc.substring(1,loc.length);
       }
       if(f&&(f.tagName+'').toLowerCase()=='form')
       { f.onSubmit = null; }

       if(!arguments||arguments.length<2||arguments[1]){
           //search
        var k = AppliTrack_$('AppliTrackPostingSearchBasic');
        var ak= AppliTrack_$('AppliTrackSearchKeyword');
        var tt= AppliTrack_$('AppliTrackSearchTitle');
        var d = AppliTrack_$('AppliTrackSearchDistrict');
        var l = AppliTrack_$('AppliTrackSearchLocation');
        var c = AppliTrack_$('AppliTrackSearchCategory');
        var sc= AppliTrack_$('AppliTrackSearchSubCategory');
        var pd= AppliTrack_$('AppliTrackSearchPostDateRange');
        var sregion = AppliTrack_$('AppliTrackSearchRegion');
        var zc =AppliTrack_$('AppliTrackZipCode');
        var zipr = AppliTrack_$('AppliTrackSearchRadius');
        var int = AppliTrack_$('internal');
        var state= AppliTrack_$('AppliTrackSearchState');

           var s = '';
           if(!AppliTrack_isEmpty(k)&&'Search Postings'!=''+k.value)
             {
               s+=(s!=''?' ':'');
               if(k.value !=''){ s+='title:' + k.value;}
             }
           if(!AppliTrack_isEmpty(ak)){s+=(s!=''?' ':'') + ak.value;}
           if(d&&d.options&&d.selectedIndex>=0&&''!=''+d.options[d.selectedIndex].value){
               for(var i=1;i < d.options.length;i++){
                   if(d.options[i].selected && d.options[i].value+''!=''){
                       s+=(s!=''?' ':'') + 'district:' + d.options[i].value;
                   }
               }
               loc = AppliTrack_RemoveParam(loc,'district');
           }
        var radius='';
        if (zipr != null)
        {
            if (zipr.value !='')
            {
            radius=' radius%3A"'+ zipr.value +'"';
            }
        }
        if (l != null)
        {
               if(l&&l.options&&''!=''+l.options[l.selectedIndex].value){
                   s+=(s!=''?' ':'') + 'location:"' + l.options[l.selectedIndex].value + '"';
                   loc = AppliTrack_RemoveParam(loc,'location');
               }
        }
           if(tt&&''!=''+tt.value){
               s+=(s!=''?' ':'') + 'title:"' + tt.value + '"';
               loc = AppliTrack_RemoveParam(loc,'title');
           }
        if(pd&&pd.options&&''!=''+pd.options[pd.selectedIndex].value){
               s+=(s!=''?' ':'') + 'dateposted:' + pd.options[pd.selectedIndex].value + '';
               loc = AppliTrack_RemoveParam(loc,'dateposted');
           }
           if(c&&c.options&&''!=''+c.options[c.selectedIndex].value){
            try{
                eval('var g = '+c.options[c.selectedIndex].value);
                s+=(s!=''?' ':'') + 'category:"' + g.id + '"';
                loc = AppliTrack_RemoveParam(loc,'category');
            }catch(e){/*malformed option*/}
           }

           if(sregion && sregion.options && sregion.options[sregion.selectedIndex] != null && ''!=''+sregion.options[sregion.selectedIndex].text){
                try{
                    s+=(s!=''?' ':'') + 'region:"' + sregion.options[sregion.selectedIndex].text + '"';
                    loc = AppliTrack_RemoveParam(loc,'region');
                }catch(e){/*malformed option*/}
           }

           if(sc&&sc.options&&!sc.disabled&&sc.selectedIndex>=0&&'' != ''+sc.options[sc.selectedIndex].value){
               s+=(s!=''?' ':'') + 'subcategory:"' + sc.options[sc.selectedIndex].value + '"';
               loc = AppliTrack_RemoveParam(loc,'subcategory');
           }

           if (typeof CustomSearchFormExtender == 'function') {
               s = s + CustomSearchFormExtender();
           }
           loc = AppliTrack_AddParam(loc,'AppliTrackPostingSearch',s);
       }
    if (zc != null){
        loc = AppliTrack_AddParam(loc,'AppliTrackZipCode', zc.value);
        loc = AppliTrack_AddParam(loc,'AppliTrackZipRadius', zipr.value);
    }
    if (state != null){
        loc = AppliTrack_AddParam(loc,'AppliTrackSearchState', state.value);
    }
    if (int != null)
    {
        loc = AppliTrack_AddParam(loc,'internal', int.value);
    }
       //sort
    var so = AppliTrack_$('AppliTrackSort');
       if(so&&so.options&&''!=''+so.options[so.selectedIndex].value){
           loc = AppliTrack_AddParam(loc ,'AppliTrackSort',''+so.options[so.selectedIndex].value);
       }

       //display
    var m = AppliTrack_$('AppliTrackLayoutMode');
       if(m&&m.options&&''!=''+m.options[m.selectedIndex].value){
           loc = AppliTrack_AddParam(loc ,'AppliTrackLayoutMode',''+m.options[m.selectedIndex].value);
       }

    //expand/collapse
    if(arguments&&arguments.length==3&&arguments[2]&&(navigator.vendor+'').indexOf('Apple')==-1){
        loc = AppliTrack_AddParam(loc,'AppliTrackSearch','expanded');
    }



    //GET
    if(loc.match(/^&/g))  {loc = loc.substring(1,loc.length);}
    if(!loc.match(/^\?/g)){loc = '?' + loc;}
    if(loc.match(/[&\?]$/)!=null){loc = loc.substr(0,loc.length-1);}
        window.location = window.location.toString().replace(window.location.search,'') + loc;

    }

    // if no zip code show this
    else
    {
        if (zcv != null){
            zcv.style.visibility="visible";
        }
    }
}


function AppliTrack_isEmpty(s){
    var st = (s&&s.value?s.value:s);
    return !(st && ''!=''+st && 'undefined'!=''+st);
}

function AppliTrack_AddParam(loc,key,val){
    var rv = loc+'';
    if(!AppliTrack_isEmpty(key)&&!AppliTrack_isEmpty(val)){
        if (rv.match(new RegExp(key+'=',"ig"))){
            rv = AppliTrack_RemoveParam(rv,key);
           }
        if(rv.length>0 && !rv.match('&$')){rv += '&';}
           rv += key + "=" + escape(val);

    }
    return rv;
}

function AppliTrack_RemoveParam(loc,key){

    var rv = (loc+'').split('&');
    if(key!= ''){
        for(var i=0;i < rv.length;i++){
           if(rv[i].substring(0,key.length) == key){
                rv[i]='';
            }
        }
    }
    return (rv?rv.join('&').replace('&&','&'):'');
}
function AppliTrack_$(id) {
    var o = null;
    if( document.layers ) {
        o = document.layers[id];
    } else if( document.all ) {
        o = document.all[id];
    } else if( document.getElementById ) {
        o = document.getElementById(id);
    }
    return o;
}


function updateEmailLinkFromCurrentWindowLocation(mailSubject, mailMsg, queryStrings)
{
    queryStrings = queryStrings.replace('default.aspx', 'JobPostings/view.asp');
    var newLine = "%0D%0A";
    var sanitizedUrl = sanitizeUrl(window.location.href, queryStrings)
    window.location.href = mailSubject + mailMsg + newLine + newLine + encodeURIComponent(sanitizedUrl);
}

function updateHrefFromCurrentWindowLocation(queryStrings, isOpenInNewTab, isClearPreviousParams, isReplaceDefault){
    var currentLocation = window.location.href;

    if(isClearPreviousParams) currentLocation =  window.location.origin + window.location.pathname;

    if(isReplaceDefault) currentLocation = currentLocation.replace('default.aspx', 'JobPostings/view.asp');

    if (currentLocation.indexOf('?') == -1 && queryStrings.indexOf('?') == -1) {
        currentLocation = currentLocation + "?";
    }
    else {
        if (currentLocation.indexOf('?') != -1) currentLocation = currentLocation + '&';
    }

    if(isOpenInNewTab)
        window.open(sanitizeUrl(currentLocation, queryStrings), '_blank' );
    else
        window.location.href = sanitizeUrl(currentLocation, queryStrings);
}

function sanitizeUrl(currentLocation, queryStrings){
    queryStrings = queryStrings.replace("ApplitrackHardcodedURL?1=1", "");
    queryStrings = queryStrings.replace("ApplitrackHardcodedURL", "");

    return removeDuplicateQueryStringsFromUrl(currentLocation + queryStrings);
}

function removeDuplicateQueryStringsFromUrl(currentLocation)
{
	// Example : "http://qa4.applitrack.com/dex/jobhomepage.html?AppliTrackSort=newest&AppliTrackSort=newest"
	var delimeter = '&';
	var newUrl = [];
	var urlArray = currentLocation.split(delimeter);

	urlArray.forEach(function(urlParameter, index)
	{
		if (newUrl.indexOf(urlParameter) == -1 && urlParameter.indexOf('?') != 0)
		{
			if((urlParameter.indexOf('/') > 0 && index == 0) || urlParameter.indexOf('=') > 0)
			{
				newUrl.push(urlParameter);
			}
		}
	});

	return newUrl.join(delimeter);
}

document.write('<div id=\'AppliTrackOutput\'><form id=\'AppliTrackSearchForm\' name=\'AppliTrackSearchForm\' onsubmit=\'return false;\'><a name=AppliTrackPostings id=AppliTrackPostings></a><link rel=\'stylesheet\' type=\'text/css\' href=\'/olacommon/jobpostings/postingStyles.v3.css?v=8-17-2016\' /><div class=\'AppliTrackListHeader\'id=\'ApplicantMain\'><div>Openings as of 11/11/2026</div></div><br><div style=\'display: none;\'>force display?True</div><div id=\'AppliTrackSearchContainer\'><table width=\'100%\' class=\'AppliTrackSearchBG\'><tr><td class="normal" width="100%">Viewing All Types&nbsp;(<b>3</b> openings)</td><td align=right nowrap><div id=\'AppliTrackSearchSimpleContainer\'><label for=\'AppliTrackPostingSearchBasic\' class=\'HiddenButReadable\'>Search Postings:</label><input type=\'text\' size=\'15\' id=\'AppliTrackPostingSearchBasic\' style=\'font-style: italic; color: #999999\' onfocus=\'AppliTrackSearchFocus()\' onblur=\'AppliTrackSearchBlur()\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\' /><input type=\'button\' value=\'Go\'&nbsp; class=\'button\' style=\'padding:0px 0px;\' onclick=\'submitAppliTrackSearch()\' /></div></td></tr></table><div id=\'AppliTrackSearchAdvancedHeaderCollapsed\' style=\'display:block;\' onclick=\'AppliTrack_ToggleAdvancedSearch()\' tabindex=\'0\' aria-role=\'button\' onkeydown=\'AppliTrack_onKeyPressToggle(event)\'>Options</div><div id=\'AppliTrackSearchAdvancedContainer\' style=\'display:none;\'><div class=\'section\' style=\'padding-bottom:4px;border-bottom:solid 1px #ddd;\'><div class=\'header\'>Search Job Postings</div><div><label for=\'AppliTrackSearchKeyword\'><span class=\'fixedCol1 label\' nowrap=\'nowrap\'><u>Posting</u> contains:</span></label><input style=\'width:250px;\' type=\'text\' name=\'AppliTrackSearchKeyword\' id=\'AppliTrackSearchKeyword\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'/></div><div><label for=\'AppliTrackSearchTitle\'><span class=\'fixedCol1 label\' nowrap=\'nowrap\'><u>Title</u> contains:</span></label><input style=\'width:250px;\' type=\'text\' name=\'AppliTrackSearchTitle\' id=\'AppliTrackSearchTitle\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\' /></div><div><span class=\'fixedCol1 label\'>In Category:</span><select name=\'AppliTrackSearchCategory\' id=\'AppliTrackSearchCategory\' onchange=\'AppliTrack_SearchCategorySelect()\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'><option style=\'color:#666;font-style: italic;\'>Select Category</option><option value=\'{id:"High School Teaching",vals:[""]}\'>High School Teaching</option><option value=\'{id:"Substitute",vals:["Substitute"]}\'>Substitute</option><option value=\'{id:"Support Staff",vals:["Instructional Assistant"]}\'>Support Staff</option></select><span class=\'label\'> and </span><span class=\'label\' style=\'white-space:nowrap\'>SubCategory:<select name=\'AppliTrackSearchSubCategory\' id=\'AppliTrackSearchSubCategory\' disabled=\'disabled\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'><option></option></select></span></div><div><span class=\'fixedCol1 label\'>At Location:</span><select name=\'AppliTrackSearchLocation\' id=\'AppliTrackSearchLocation\' onchange=\'AppliTrack_RadiusSelect()\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'><option value=\'\' style=\'font-style:italic;color:#999\'> -- Any Location -- </option><option value="Dickenson County Public Schools">Dickenson County Public Schools</option><option value="Ridgeview High School">Ridgeview High School</option></select></div><div id="AppliTrackSearchZipCodeSection"><span class=\'fixedCol1 label\'>Within:</span><select name=\'AppliTrackSearchRadius\' id=\'AppliTrackSearchRadius\' onchange=\'AppliTrack_SearchCategorySelect()\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'><option value=\'5\'>5</option><option value=\'10\'>10</option><option value=\'15\'>15</option><option value=\'25\'>25</option><option value=\'50\'>50</option><option value=\'100\'>100</option><option value=\'150\'>150</option></select><span class=\'fixedCol1 label\' style=\'margin-left: -25px;\'>miles of Zip:</span><label for=\'AppliTrackZipCode\' class=\'HiddenButReadable\'>Zip Code</label><input style=\'width:70px;\' type=\'text\' name=\'AppliTrackZipCode\' id=\'AppliTrackZipCode\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\' /><stronge name=\'AppliTrackZipValidator\' id=\'AppliTrackZipValidator\' style=\'visibility:hidden;text-align: left;color:red;\'>Invalid Zipcode</stronge><input style=\'width:250px;\' type=\'hidden\' name=\'internal\' id=\'internal\' value=\'\'&nbsp; /></div><button id="AppliTrackSearchButton" type="button" style=\'float:right;margin-right:10px;cursor:pointer;\' onclick=\'AppliTrack_SearchExecute(null)\'>Search</button><div><span class=\'label\' style=\'width:125px;text-align:right;\'>Posted in the last:</span><select name=\'AppliTrackSearchPostDateRange\' id=\'AppliTrackSearchPostDateRange\' onKeyPress=\'return AppliTrack_WatchForEnter(event)\'><option value=\'\'>All Dates</option><option value=\'7\'>7 Days</option><option value=\'14\'>14 Days</option><option value=\'30\'>30 Days</option></select></div></div><div class=\'section\' style=\'vertical-align: top;\'><span style=\'white-space:nowrap\'><span class=\'header\'>Sort Results By:</span><select name=\'AppliTrackSort\' id=\'AppliTrackSort\' class=\'data\'><option class=\'data\' value=\'type\' selected=\'selected\'>type</option><option class=\'data\' value=\'title\'>title</option><option class=\'data\' value=\'location\'>location</option><option class=\'data\' value=\'newest\'>newest</option><option class=\'data\' value=\'oldest\'>oldest</option></select></span><span style=\'white-space:nowrap\'><span class=\'header\'>Display as:</span><select name=\'AppliTrackLayoutMode\' id=\'AppliTrackLayoutMode\' class=\'data\'><option value=\'detail\' selected=\'selected\'>Detailed View</option><option value=\'condensed\'>Condensed View</option></select></span></div></div><div id=\'AppliTrackSearchAdvancedHeaderExpanded\' style=\'display:none;\' onclick=\'AppliTrack_ToggleAdvancedSearch()\'>Options</div></div><div id=\'AppliTrackListContent\'><p align=center class=noprint id=\'p1367_h\'><span class=\'ListHeader\'>Openings as of 11/11/2026<br/></span></p><ul class=\'postingsList\' id=\'p1367_\'><table class=\'title\' style=\'padding: 0px; width:99.2%\'><tr><td id=\'wrapword\' style=\'width: 950px; padding: 5px;\'>Teacher Aide(s) - Part Time Position(s)</td><td style=\'width: 275px;\'><span class=\'title2\' style=\'float:right;text-align:right;margin-top: 8px;margin-right: 6px;\'> JobID: 1367 <input type=\'button\' value=\' Apply \' onclick="applyFor(\'1367\',\'Support Staff\',\'Instructional Assistant\')" class=\'screenOnly ApplyButton\' /></span></td></tr></table><div style=\'position:relative;\'><li><span class=\'label\'>Position Type:</span><br/>&nbsp;&nbsp;<span class=\'normal\'>Support Staff/</span><span class=\'normal\'>Instructional Assistant</span><br/><br/></li><li><span class="label" >Date Posted:</span><br/>&nbsp;&nbsp;<span class="normal">9/11/2026</span><br/><br/></li><li><span class="label" >Location:</span><br/>&nbsp;&nbsp;<span class="normal">Dickenson County Public Schools</span><br/><br/></li><span>&nbsp&nbsp</span><span class="label" >Additional Information: &nbsp;</span><span class="normal"><a href="javascript:void(toggle_block(\'DescriptionText1367_\'))"><u>Show/Hide</u></a></span><br/><span id=\'DescriptionText1367_\' style=\'border: 1px solid black; padding:5px; display:none; opacity:.8;\'><span class="normal"><p><strong>The Dickenson County School System is accepting applications for the following possible vacancies:</strong><br>&nbsp;<br><strong>SUPPORT POSITIONS&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <u>Teacher Aide(s) – Part Time Position(s)</u></strong><br>&nbsp;<br>Applicants must have one of the following requirements - (1) two years of college (60 semester hours), (2) an Associate Degree, or (3) have passed the Para Pathways assessment.&nbsp; <u>Please provide proof of meeting at least one of these requirements with your application, i.e. transcripts, copy of degree, or Para Pro test scores.&nbsp; Applications cannot be considered without this documentation.</u><br>&nbsp;<br><u>If you do not have one of the three requirements listed above, but are interested in the position, please contact the Dickenson County School Board Office and ask about taking the Para Pathways assessment which is given at the school board office. Contact the office at [phone].</u><br>&nbsp;<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<br><strong>APPLICATION DEADLINE</strong>&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<strong>Open until Filled</strong><br>&nbsp;<br>&nbsp;<br><strong>RECRUITMENT, SELECTION</strong>&nbsp;&nbsp;&nbsp; The school board reserves the right to consider those who respond, and<br><strong>AND APPOINTMENT&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; </strong>any other potential candidates.<br>&nbsp;<br>&nbsp;<br><strong>APPLICATION PROCESS</strong>&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Qualified persons may apply online by visiting the Dickenson County Schools website at <a target="_blank" rel="noopener noreferrer" href="http://www.dcps.k12.va.us/">www.dcps.k12.va.us</a>.&nbsp; Go to the Employment tab and look for Vacancies.&nbsp;<br><br><br>Mrs. Deirdre Deel, Director of Personnel<br>Dickenson County Schools<br>P.O. 1127<br>Clintwood, VA&nbsp; 24228<br>Phone [phone]<br>&nbsp;<br><strong>DICKENSON COUNTY SCHOOLS – AN EQUAL OPPORTUNITY EMPLOYER</strong><br>&nbsp;<br>&nbsp;<br>Civil Rights Notice of Nondiscrimination statement:<br>Dickenson County Public Schools does not discriminate on the basis of race, color, national origin, sex, disability, or age in its programs and activities; and provides equal access to the Boy Scouts and other designated youth groups.&nbsp; The following person has been designated to handle inquiries regarding the nondiscrimination policies: Karen Martin, Title IX Coordinator (hr@example.org) or Jesse Neece, Section 504 Coordinator (hr@example.org)<br>PO Box 1127<br>Clintwood, VA&nbsp; 24228 [phone]<br>&nbsp;</p></span><br /><img src=\'https://www.applitrack.com/clear.gif\' height=8><br /></span><div class="AppliTrackJobPostingAttachments">Attachment(s):<ul><li><a rel="nofollow" target="_blank" href="https://www.applitrack.com/dcps/onlineapp/1BrowseFile.aspx?id=5425">Part-Time Aide.docx</a></li></ul></div><br/><div class=\'label\' align=\'right\' style=\'position:absolute; top:0%;right:1%;\'><span class=\'s\'>');
document.write('<div class="addthis_toolbox addthis_default_style "><a class="addthis_button_preferred_1"></a><a class="addthis_button_preferred_2"></a><a class="addthis_button_preferred_3"></a><a class="addthis_button_compact"></a><a class="addthis_counter addthis_bubble_style"></a></div><script type="text/javascript" src="https://s7.addthis.com/js/250/addthis_widget.js#pubid=ra-4dfeb954767d3dc8"></script><br><a href=\'javascript:updateEmailLinkFromCurrentWindowLocation("mailto:?subject=Job Posting&body=","I thought you would be interested in an employment opportunity I found at Dickenson County Schools. The position is Teacher Aide(s) - Part Time Position(s). Please click the link below for more information about this vacancy.","ApplitrackHardcodedURL?1=1&AppliTrackJobId=1367&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1")\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Email To A Friend</span></a><br/><a href=\'javascript:updateHrefFromCurrentWindowLocation("ApplitrackHardcodedURL?1=1&AppliTrackJobId=1367&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1" , true, false, true)\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Print Version</span> </a><br/></span></div><br/></div></ul><div style=\'width: 100%; height: .75px; background: gray; overflow: hidden; margin-bottom:4px;\'></div><br /><p align=center class=noprint id=\'p1391_h\'><span class=\'ListHeader\'>Openings as of 11/11/2026<br/></span></p><ul class=\'postingsList\' id=\'p1391_\'><table class=\'title\' style=\'padding: 0px; width:99.2%\'><tr><td id=\'wrapword\' style=\'width: 950px; padding: 5px;\'>Auto Collision Instructor</td><td style=\'width: 275px;\'><span class=\'title2\' style=\'float:right;text-align:right;margin-top: 8px;margin-right: 6px;\'> JobID: 1391 <input type=\'button\' value=\' Apply \' onclick="applyFor(\'1391\',\'High School Teaching\',\'\')" class=\'screenOnly ApplyButton\' /></span></td></tr></table><div style=\'position:relative;\'><li><span class=\'label\'>Position Type:</span><br/>&nbsp;&nbsp;<span class=\'normal\'>High School Teaching</span><br/><br/></li><li><span class="label" >Date Posted:</span><br/>&nbsp;&nbsp;<span class="normal">3/30/2026</span><br/><br/></li><li><span class="label" >Location:</span><br/>&nbsp;&nbsp;<span class="normal">Ridgeview High School</span><br/><br/></li><span>&nbsp&nbsp</span><span class="label" >Additional Information: &nbsp;</span><span class="normal"><a href="javascript:void(toggle_block(\'DescriptionText1391_\'))"><u>Show/Hide</u></a></span><br/><span id=\'DescriptionText1391_\' style=\'border: 1px solid black; padding:5px; display:none; opacity:.8;\'><span class="normal"><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>TEACHING POSITION&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong><u>&nbsp;Auto Collision Instructor</u></strong></span></p><p>&nbsp;</p><ul><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="eddf056c15815bbb8bcab2bdeda76806d"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">At least&nbsp;<strong>two years&nbsp;</strong>of successful experience in the field of auto collision repair within the&nbsp;<strong>last five years.</strong></span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="ea31e53bbfc32675c6f3338346558d715"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Certification and licenses in the field – Must have or be willing to obtain the ASE: Paint and Refinishing Certification.&nbsp; (Test B Series-B2), OSHA, etc.</span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="e50b197e1cb1276ae535a6e6f1734b570"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Must hold or be eligible for Virginia Teaching Licensure with the appropriate endorsement area(s.)</span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="e35c734262a8ab20f2185e3f04ff182bb"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Demonstrate the aptitude and competence necessary for assigned responsibilities.</span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="e382e1e3522309e969d7634cf59461fb9"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Demonstrate excellent communication skills, computer skills, and the ability to make independent decisions in accordance with established policies and procedures.</span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="e6d54f92be0dcfe620985b6f8869b5556"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Leadership qualities as well as personal and professional characteristics required to work effectively with students, teachers, support staff, and parents.</span></li><li class="ck-list-marker-font-size ck-list-marker-font-family" style="--ck-content-list-marker-font-family:&quot;Arial&quot;,sans-serif;--ck-content-list-marker-font-size:10.0pt;" data-list-item-id="e6c4b7e06b2e21d234efb9aa3ab90ca05"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Other qualifications the school board may finds appropriate.</span></li></ul><p style="margin-left:1.0in;text-align:center;">&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>APPLICATION DEADLINE &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;Open Until Filled.</strong></span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>RECRUITEMENT, SELECTION, &nbsp; &nbsp; &nbsp;&nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">The school board reserves the right to consider those&nbsp;</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>AND APPOINTMENT</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;who respond, and any other potential candidates.</span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>APPLICATION PROCESS &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">Please apply online by visiting the Dickenson County &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Public Schools website at&nbsp;</span><a target="_blank" rel="noopener noreferrer" href="http://www.dcps.k12.va.us"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">www.dcps.k12.va.us</span></a><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">.&nbsp; Go&nbsp;</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; to the Employment tab and look for Vacancies.</span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Deirdre Deel, Director of Personnel</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Dickenson County Public Schools</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; PO Box 1127</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Clintwood VA&nbsp; 24228&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:9.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Phone [phone]</span></p><p>&nbsp;</p><p>&nbsp;</p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:8.0pt;"><strong>DICKENSON COUNTY PUBLIC SCHOOLS – AN EQUAL OPPORTUNITY EMPLOYER</strong></span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">Civil Rights Notice of Nondiscrimination statement:</span></p><p style="text-align:justify;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">Dickenson County Public Schools does not discriminate on the basis of race, color, national origin, sex, disability, or age in its programs and activities and provides equal access to the Boy Scouts and other designated youth groups.&nbsp; The following person has been designated to handle inquiries regarding the nondiscrimination policies:&nbsp; Karen Martin, Title IX Coordinator (</span><a href="mailto:hr@example.org"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">hr@example.org</span></a><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">) or Denechia Edwards, Section 504 Coordinator</span></p><p style="text-align:justify;">&nbsp;</p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">PO Box 1127</span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">Clintwood VA&nbsp; 24228</span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:6.0pt;">[phone]</span></p><p style="text-align:center;">&nbsp;</p><p>&nbsp;</p></span><br /><img src=\'https://www.applitrack.com/clear.gif\' height=8><br /></span><div class="AppliTrackJobPostingAttachments">Attachment(s):<ul><li><a rel="nofollow" target="_blank" href="https://www.applitrack.com/dcps/onlineapp/1BrowseFile.aspx?id=5134">Auto Collision Instructor.docx</a></li></ul></div><br/><div class=\'label\' align=\'right\' style=\'position:absolute; top:0%;right:1%;\'><span class=\'s\'><div class="addthis_toolbox addthis_default_style "><a class="addthis_button_preferred_1"></a><a class="addthis_button_preferred_2"></a><a class="addthis_button_preferred_3"></a><a class="addthis_button_compact"></a><a class="addthis_counter addthis_bubble_style"></a></div><script type="text/javascript" src="https://s7.addthis.com/js/250/addthis_widget.js#pubid=ra-4dfeb954767d3dc8"></script><br><a href=\'javascript:updateEmailLinkFromCurrentWindowLocation("mailto:?subject=Job Posting&body=","I thought you would be interested in an employment opportunity I found at Dickenson County Schools. The position is Auto Collision Instructor. Please click the link below for more information about this vacancy.","ApplitrackHardcodedURL?1=1&AppliTrackJobId=1391&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1")\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Email To A Friend</span></a><br/>');
document.write('<a href=\'javascript:updateHrefFromCurrentWindowLocation("ApplitrackHardcodedURL?1=1&AppliTrackJobId=1391&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1" , true, false, true)\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Print Version</span> </a><br/></span></div><br/></div></ul><div style=\'width: 100%; height: .75px; background: gray; overflow: hidden; margin-bottom:4px;\'></div><br /><p align=center class=noprint id=\'p1387_h\'><span class=\'ListHeader\'>Openings as of 11/11/2026<br/></span></p><ul class=\'postingsList\' id=\'p1387_\'><table class=\'title\' style=\'padding: 0px; width:99.2%\'><tr><td id=\'wrapword\' style=\'width: 950px; padding: 5px;\'>Substitute</td><td style=\'width: 275px;\'><span class=\'title2\' style=\'float:right;text-align:right;margin-top: 8px;margin-right: 6px;\'> JobID: 1387 <input type=\'button\' value=\' Apply \' onclick="applyFor(\'1387\',\'Substitute\',\'Substitute\')" class=\'screenOnly ApplyButton\' /></span></td></tr></table><div style=\'position:relative;\'><li><span class=\'label\'>Position Type:</span><br/>&nbsp;&nbsp;<span class=\'normal\'>Substitute/</span><span class=\'normal\'>Substitute</span><br/><br/></li><li><span class="label" >Date Posted:</span><br/>&nbsp;&nbsp;<span class="normal">2/11/2026</span><br/><br/></li><li><span class="label" >Location:</span><br/>&nbsp;&nbsp;<span class="normal">Dickenson County Public Schools</span><br/><br/></li><span>&nbsp&nbsp</span><span class="label" >Additional Information: &nbsp;</span><span class="normal"><a href="javascript:void(toggle_block(\'DescriptionText1387_\'))"><u>Show/Hide</u></a></span><br/><span id=\'DescriptionText1387_\' style=\'border: 1px solid black; padding:5px; display:none; opacity:.8;\'><span class="normal"><p>&nbsp;</p><p><span style="color:hsl(0,75%,60%);font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>After your substitute application has been reviewed and accepted, you will receive an email instructing you to set up a Frontline account and start your Substitute Onboarding Packet. &nbsp;You will need to follow all of the instrctions and complete each step. &nbsp;After all steps have been completed, and your background check has been received, and you have been approved by the School Board, you will then be able to accept substitute jobs in our Frontline system.</strong></span></p><p style="text-align:center;">&nbsp;</p><p style="text-align:center;">&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>SUPPORT POSITION(S)&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; Substitute (Teacher, Cook, Custodian, Nurse, Bus Driver)</strong></span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>APPLICATION DEADLINE &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;"><strong>Open Until Filled</strong></span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>RECRUITEMENT, SELECTION, &nbsp;&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">The school board reserves the right to consider those&nbsp;</span></p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>AND APPOINTMENT</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; who respond, and any other potential candidates.</span></p><p>&nbsp;</p><p><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:11.0pt;"><strong>APPLICATION PROCESS &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;</strong></span><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">Please apply online by visiting the Dickenson County &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Public Schools website at&nbsp;</span><a target="_blank" rel="noopener noreferrer" href="http://www.dcps.k12.va.us"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">www.dcps.k12.va.us</span></a><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">.&nbsp; Go&nbsp;</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;to the Employment tab and look for Vacancies.</span></p><p style="margin-left:3.0in;">&nbsp;</p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Deirdre Deel, Director of Personnel</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Dickenson County Public Schools</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;PO Box 1127</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Clintwood VA&nbsp; 24228&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span></p><p style="margin-left:3.0in;"><span style="font-family:&quot;Arial&quot;,sans-serif;font-size:10.0pt;">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;Phone [phone]</span></p><p style="margin-left:3.0in;">&nbsp;</p><p style="margin-left:3.0in;">&nbsp;</p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:8.0pt;"><strong>DICKENSON COUNTY PUBLIC SCHOOLS – AN EQUAL OPPORTUNITY EMPLOYER</strong></span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">Civil Rights Notice of Nondiscrimination statement:</span></p><p style="text-align:justify;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">Dickenson County Public Schools does not discriminate on the basis of race, color, national origin, sex, disability, or age in its programs and activities and provides equal access to the Boy Scouts and other designated youth groups.&nbsp; The following person has been designated to handle inquiries regarding the nondiscrimination policies:&nbsp; Karen Martin, Title IX Coordinator (</span><a href="mailto:hr@example.org"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">hr@example.org</span></a><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">) or Jesse Neece, 504 Coordinator</span></p><p style="text-align:justify;">&nbsp;</p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">PO Box 1127</span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">Clintwood VA&nbsp; 24228</span></p><p style="text-align:center;"><span style="font-family:&quot;Tahoma&quot;,sans-serif;font-size:12px;">[phone]</span></p><p style="text-align:center;">&nbsp;</p><p>&nbsp;</p></span><br /><img src=\'https://www.applitrack.com/clear.gif\' height=8><br /></span><br/><div class=\'label\' align=\'right\' style=\'position:absolute; top:0%;right:1%;\'><span class=\'s\'><div class="addthis_toolbox addthis_default_style "><a class="addthis_button_preferred_1"></a><a class="addthis_button_preferred_2"></a><a class="addthis_button_preferred_3"></a><a class="addthis_button_compact"></a><a class="addthis_counter addthis_bubble_style"></a></div><script type="text/javascript" src="https://s7.addthis.com/js/250/addthis_widget.js#pubid=ra-4dfeb954767d3dc8"></script><br><a href=\'javascript:updateEmailLinkFromCurrentWindowLocation("mailto:?subject=Job Posting&body=","I thought you would be interested in an employment opportunity I found at Dickenson County Schools. The position is Substitute. Please click the link below for more information about this vacancy.","ApplitrackHardcodedURL?1=1&AppliTrackJobId=1387&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1")\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Email To A Friend</span></a><br/><a href=\'javascript:updateHrefFromCurrentWindowLocation("ApplitrackHardcodedURL?1=1&AppliTrackJobId=1387&AppliTrackLayoutMode=detail&AppliTrackViewPosting=1" , true, false, true)\'><span style=\'color:#4c4c4c;font-size:.9em;font-weight:normal;\'>Print Version</span> </a><br/></span></div><br/></div></ul><div style=\'width: 100%; height: .75px; background: gray; overflow: hidden; margin-bottom:4px;\'></div><br />');
function setUpPageBreaks(){h = 0; try{AppliTrack_$('p1391_h').className = 'noprint'; if (h + AppliTrack_$('p1391_').clientHeight > 775){h = 0; AppliTrack_$('p1391_h').className = 'printOnly'; } h = h + AppliTrack_$('p1391_').clientHeight; AppliTrack_$('p1387_h').className = 'noprint'; if (h + AppliTrack_$('p1387_').clientHeight > 775){h = 0; AppliTrack_$('p1387_h').className = 'printOnly'; } h = h + AppliTrack_$('p1387_').clientHeight; }catch(ex){}}
var h = 0
setTimeout("setUpPageBreaks()",100)
document.write('</div><span class=\'screenOnly\'><div class="subnotetext"></div></span><noscript>Powered by Aspex Solutions - AppliTrack, Applicant Tracking for Educators. Online Job Employment Applications, Web Based Employment Applications for School Districts and Educational Institutions - <a href=http://www.aspexsolutions.com/home/>www.aspexsolutions.com</a></noscript><noscript>You can also view <a href=\'http://www.k12jobspot.com/virginia-teaching-jobs\'>Virginia teaching jobs</a> at www.k12jobspot.com. K12JobSpot is a site that has thousands of teaching jobs - all from AppliTrack school districts.</noscript></form></div>');
var gaJsHost = (("https:" == document.location.protocol) ? "https://ssl." : "http://www."); document.write(unescape("%3Cscript src='" + gaJsHost + "google-analytics.com/ga.js' type='text/javascript'%3E%3C/script%3E"));try {var pageTracker = _gat._getTracker("UA-12436368-1");pageTracker._trackPageview();} catch(err) {}