import sys
import json
import re
import ssl
import threading
import webbrowser
import socketserver
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 6789
PROXY_HOST = f"http://localhost:{PORT}"
PROXY_HOST_ALT = f"http://127.0.0.1:{PORT}"

CHANNELS = {
    # -- Web players --
    "1": {"name": "Willow TV",               "url": "https://dadocric.st/player.php?id=willow",      "type": "web"},
    "2": {"name": "Willow Extra",             "url": "https://dadocric.st/player.php?id=willowextra", "type": "web"},
    "3": {"name": "PTV Sports",               "url": "https://dadocric.st/player.php?id=ptvsp",       "type": "web"},
    "4": {"name": "CricGo 2",                 "url": "https://dadocric.st/player.php?id=cricgo2",     "type": "web"},
    "5": {"name": "Star Sports 1 (Web)",      "url": "https://dadocric.st/player.php?id=ss1",         "type": "web"},
    "6": {"name": "Star Sports 2 (Web)",      "url": "https://dadocric.st/player.php?id=ss2",         "type": "web"},
    "7": {"name": "Star Sports 1 Hindi (Web)","url": "https://dadocric.st/player.php?id=ss1hindi",    "type": "web"},
    # --- Live HLS Streams ---
    "8": {"name": "Willow Sports",            "url": "https://d36r8jifhgsk5j.cloudfront.net/Willow_TV.m3u8", "type": "hls"},
    "9": {"name": "Cricket Gold",             "url": "https://streams2.sofast.tv/scheduler/scheduleMaster/418.m3u8", "type": "hls"},
    "10": {"name": "DSTV (614p)",             "url": "http://46.249.95.140:8081/hls/data.m3u8",                 "type": "hls"},
    "11": {"name": "Star Sports 2 (Old)",     "url": "http://tvn1.chowdhury-shaheb.com/starsport2/index.m3u8", "type": "hls"},
}


_AD_PAT = '|'.join([
    'adzilla', r'1win\.', 'doubleclick', 'googlesyndication',
    'amazon-adsystem', r'openx\.net', r'pubmatic\.com', 'rubiconproject',
    'taboola', 'outbrain', r'adsrvr\.org', 'propellerads', r'popcash\.net',
    'exoclick', 'trafficjunky', 'trafficstars', 'adsterra',
    'hilltopads', 'juicyads', 'plugrush', 'clickadu',
    'chatango', r'cbox\.ws',
])

_INJECT = (
    '<style>'
    '[class*="advert"],[id*="advert"],'
    '[class*="adzilla"],[id*="adzilla"],'
    '[class*="popup"],[id*="popup"],'
    '[class*="ChatBox"],[id*="ChatBox"],'
    '.chatWrap,#chatWrap,.chat-wrap,#chat-wrap,'
    '.chatBox,#chatBox,.chatbox,#chatbox,'
    '#floated,header,nav,footer,'
    '[id*="cid00200"],'
    '.col-span-3'
    '{display:none!important}'
    # Hide chat widget (Chatango) in all forms — including CricHD right-panel wrappers
    '#ch,[id*="chatango"],[class*="chatango"],'
    '#cxch,[id*="cxch"],[class*="cxch"],'
    '#cxbox,[id*="cxbox"],[class*="cxbox"],'
    'iframe[src*="chatango"],iframe[src*="cbox.ws"],'
    '[id*="chat-box"],[class*="chat-box"],'
    '.right-panel,.rightPanel,#right-panel,#rightPanel'
    '{display:none!important}'
    # Hide fixed/absolute overlays that are NOT the unmute button (handled by JS instead)
    'button[style*="background"][style*="position"],'
    'div[style*="position: absolute"][style*="top: -65"]'
    '{display:none!important}'
    '</style>'
    f'<script>var __PXY_BASE="{PROXY_HOST}/proxy?url=";var __PXY_BASE_ALT="{PROXY_HOST_ALT}/proxy?url=";'
    'window.open=function(){return null;};'
    '(function(){'
    'var AD=/1win|adzilla|casino|superbonus|clickadu|exoclick|trafficjunky|propellerads|geographicalpaperworkmovie|aclib|histats|adservice|doubleclick|googlesyndication|adnxs|taboola|outbrain|popcash|adroll|banner/i;'
    'var AD_IFRAME=/doubleclick|googlesyndication|geographicalpaperworkmovie|aclib|histats|chatango|adservice|popcash|adnxs|taboola|outbrain|adroll/i;'
    'var UNLOCK=/UNLOCK|CLICK\\s*\\(\\s*\\d+\\s*S\\s*\\)|CLICK TO WATCH|TAP TO UNLOCK/i;'
    'function absUrl(u){try{return new URL(u,window.location.href).href;}catch(e){return "";}}'
    'function proxyIframe(el){'
    'var raw=el.getAttribute("src")||"";'
    'if(!raw)return;'
    'if(raw.indexOf("/proxy?url=")===0||raw.indexOf(__PXY_BASE)===0||raw.indexOf(__PXY_BASE_ALT)===0)return;'
    'if(/^(about:|javascript:|data:|blob:)/i.test(raw))return;'
    'var abs=absUrl(raw);if(!abs)return;'
    'if(abs.indexOf(__PXY_BASE)===0||abs.indexOf(__PXY_BASE_ALT)===0)return;'
    'if(AD_IFRAME.test(abs)){el.style.display="none";el.src="about:blank";return;}'
    'if(/^https?:/i.test(abs)){el.setAttribute("src",__PXY_BASE+encodeURIComponent(abs));}'
    '}'
    'function setMediaMute(muted){'
    'document.querySelectorAll("video,audio").forEach(function(m){'
    'try{m.muted=!!muted;if(!muted)m.volume=1;}catch(e){}'
    '});'
    '}'
    'function fanoutControl(cmd){'
    'document.querySelectorAll("iframe").forEach(function(fr){'
    'try{if(fr.offsetWidth>100&&fr.offsetHeight>100){if(fr&&fr.contentWindow){fr.contentWindow.postMessage({__LOCAL_PROXY_CTRL__:cmd},"*");}}}catch(e){}'
    '});'
    '}'
    'function clickUnmuteButtons(){'
    'document.querySelectorAll("button,div,span,a,input").forEach(function(el){'
    'var txt=((el.textContent||el.value||el.getAttribute("aria-label")||"")+"").replace(/\\s+/g," ").trim().toUpperCase();'
    'if(/UNMUTE|SOUND ON|TURN ON SOUND|ENABLE SOUND|AUDIO ON/.test(txt)){'
    'try{el.click();}catch(e){}'
    '}'
    '});'
    '}'
    'function forceUnmute(){'
    'setMediaMute(false);'
    'fanoutControl("unmute");'
    'clickUnmuteButtons();'
    'try{'
    'if(window.player){'
    'if(typeof window.player.unMute==="function")window.player.unMute();'
    'if(typeof window.player.unmute==="function")window.player.unmute();'
    'if(typeof window.player.setVolume==="function")window.player.setVolume(100);'
    'if("muted" in window.player)window.player.muted=false;'
    '}'
    '}catch(e){}'
    '}'
    'function killAds(){'
    # First pass: unmute buttons — unhide them if CSS hid them, click, then re-hide
    'document.querySelectorAll("button,div,span,a,input,p").forEach(function(el){'
    'var txt=((el.textContent||el.value||el.getAttribute("aria-label")||"")+"").replace(/\\s+/g," ").trim().toUpperCase();'
    'if(/UNMUTE|CLICK HERE TO UNMUTE|SOUND ON|TURN ON SOUND|ENABLE SOUND|AUDIO ON/.test(txt)&&txt.length<60){'
    'var prev=el.style.display;'
    'el.style.display="";'
    'try{el.click();el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true}));}catch(e){}'
    'el.style.display="none";'
    'return;'
    '}'
    '});'
    'forceUnmute();'
    # Proxy runtime-created iframes and remove only known ad iframes
    'document.querySelectorAll("iframe").forEach(proxyIframe);'
    # Hide elements whose text content contains adzilla (catches image-based ads by their link text)
    'document.querySelectorAll("a,div,section,aside").forEach(function(el){'
    'if(/adzilla/i.test(el.textContent||"")){'
    'el.style.display="none";'
    '}'
    '});'
    # Auto-click and hide the UNLOCK / overlay buttons
    'document.querySelectorAll("button,div,span,a,input").forEach(function(el){'
    'var txt=((el.textContent||el.value||el.getAttribute("aria-label")||"")+"").replace(/\\s+/g," ").trim().toUpperCase();'
    'if(UNLOCK.test(txt)||txt==="CLICK"){'
    'try{el.click();}catch(e){}'
    'el.style.pointerEvents="none";'
    'el.style.display="none";'
    '}'
    '});'
    # Kill the floated ad div
    'var f=document.getElementById("floated");if(f)f.style.display="none";'
    # Kill header/nav/footer
    'document.querySelectorAll("header,nav,footer").forEach(function(e){e.style.display="none";});'
    # Walk up from ad anchor links and hide their container
    'document.querySelectorAll("a").forEach(function(a){'
    'if(AD.test(a.href||"")||AD.test(a.getAttribute("data-href")||"")){'
    'var el=a;'
    'for(var i=0;i<8;i++){'
    'var p=el.parentElement;'
    'if(!p||p===document.body)break;'
    'if(el.offsetWidth>100&&el.offsetHeight>80){el.style.display="none";break;}'
    'el=p;}'
    '}'
    '});'
    # Also hide images linking to ad domains
    'document.querySelectorAll("img").forEach(function(img){'
    'if(AD.test(img.src||"")){'
    'var el=img;'
    'for(var i=0;i<6;i++){'
    'var p=el.parentElement;'
    'if(!p||p===document.body)break;'
    'if(el.offsetWidth>100)el.style.display="none";'
    'el=p;}'
    '}'
    '});'
    # Kill Chatango
    'document.querySelectorAll("[id*=cid00200],script[src*=chatango]").forEach(function(e){e.style.display="none";e.remove();});'
    # Hide intrusive fixed overlays that are usually ad layers
    'document.querySelectorAll("div,section,aside").forEach(function(el){'
    'var st="";try{st=(el.getAttribute("style")||"").toLowerCase();}catch(e){}'
    'if(!st)return;'
    'if((st.indexOf("position:fixed")>-1||st.indexOf("position: fixed")>-1) && (st.indexOf("z-index")>-1||st.indexOf("top:")>-1)){'
    'if((el.offsetWidth>240&&el.offsetHeight>120)||AD.test(el.textContent||"")){el.style.display="none";}'
    '}'
    '});'
    '}'
    # Block ad links navigation inside proxied pages
    'document.addEventListener("click",function(ev){'
    'var a=ev.target&&ev.target.closest?ev.target.closest("a"):null;'
    'if(!a)return;'
    'var h=(a.href||a.getAttribute("data-href")||"");'
    'if(AD.test(h)||AD_IFRAME.test(h)){ev.preventDefault();ev.stopPropagation();a.style.display="none";}'
    '},true);'
    'document.addEventListener("click",function(){forceUnmute();},true);'
    # Receive cross-origin commands from parent page for audio control
    'window.addEventListener("message",function(ev){'
    'var d=ev&&ev.data;'
    'if(!d||typeof d!=="object")return;'
    'if(d.__LOCAL_PROXY_CTRL__==="unmute"){setMediaMute(false);clickUnmuteButtons();fanoutControl("unmute");killAds();}'
    'if(d.__LOCAL_PROXY_CTRL__==="mute"){setMediaMute(true);fanoutControl("mute");}'
    'if(d.__LOCAL_PROXY_CTRL__==="fsvid"){'
    'var vids=document.querySelectorAll("video");'
    'if(vids.length>0){'
    'document.documentElement.style.cssText="background:#000!important";'
    'document.body.style.cssText="margin:0!important;padding:0!important;background:#000!important;overflow:hidden!important";'
    'vids.forEach(function(v){v.style.cssText="position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;z-index:99999!important;object-fit:contain!important";});'
    'return;'
    '}'
    'var _skipPat=/chatango|cbox\\.ws|doubleclick|googlesyndication|adzilla|adnxs|taboola|outbrain|popcash|chat\\.js/i;'
    'var biggest=null,bigArea=0,videoFr=null;'
    'document.querySelectorAll("iframe").forEach(function(f){'
    'var s=(f.src||f.getAttribute("src")||"");'
    'if(_skipPat.test(s))return;'
    'try{if(!videoFr&&f.contentDocument&&f.contentDocument.querySelectorAll("video").length>0)videoFr=f;}catch(e){}'
    'var a=f.offsetWidth*f.offsetHeight;if(a>bigArea){bigArea=a;biggest=f;}'
    '});'
    'var pf=videoFr||biggest;'
    'if(!pf||bigArea===0){setTimeout(function(){window.postMessage({__LOCAL_PROXY_CTRL__:"fsvid"},"*");},700);return;}'
    'var el=pf;'
    'while(el&&el.parentElement&&el.parentElement!==document.documentElement){'
    'var par=el.parentElement;'
    'Array.from(par.children).forEach(function(ch){if(ch!==el)ch.style.setProperty("display","none","important");});'
    'el=par;'
    '}'
    'document.documentElement.style.setProperty("background","#000","important");'
    'document.body.style.setProperty("background","#000","important");'
    'document.body.style.setProperty("margin","0","important");'
    'document.body.style.setProperty("overflow","hidden","important");'
    'pf.style.cssText="position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;z-index:99999!important;border:none!important;display:block!important";'
    'document.querySelectorAll("iframe").forEach(function(f){try{f.contentWindow.postMessage({__LOCAL_PROXY_CTRL__:"fsvid"},"*");}catch(e){}});'
    '}'
    '});'
    'document.addEventListener("DOMContentLoaded",killAds);'
    'setTimeout(killAds,300);setTimeout(killAds,1000);setTimeout(killAds,3000);setTimeout(killAds,6000);'
    'setTimeout(forceUnmute,200);setTimeout(forceUnmute,900);setTimeout(forceUnmute,2200);setTimeout(forceUnmute,5000);setTimeout(forceUnmute,9000);'
    'setInterval(killAds,1500);'
    'var mo=new MutationObserver(killAds);'
    'mo.observe(document.documentElement,{childList:true,subtree:true});'
    # Double-click → postMessage to parent (capture phase so player handlers can't block it)
    'function _sendDbl(){try{window.top.postMessage({__LOCAL_PROXY_CTRL__:"dblclick"},"*");}catch(ex){}}'
    'document.addEventListener("dblclick",_sendDbl,true);'
    'window.addEventListener("dblclick",_sendDbl,true);'
    '})();'
    '</script>'
)

_INJECT_LIGHT = (
    '<style>'
    '#floated,header,nav,footer,[id*="cid00200"],'
    '[class*="chat"],[id*="chat"],[class*="Chat"],[id*="Chat"],'
    '#ch,[id*="chatango"],[class*="chatango"],'
    '#cxch,[id*="cxch"],[class*="cxch"],'
    '#cxbox,[id*="cxbox"],[class*="cxbox"],'
    'iframe[src*="chatango"],iframe[src*="cbox.ws"],'
    'iframe[src*="chatango" i],iframe[src*="cbox" i],'
    '.right-panel,.rightPanel,#right-panel,#rightPanel,'
    '.col-span-3,.col-md-3,.col-lg-3,.col-sm-3,'
    '[class*="adzilla"],[id*="adzilla"],'
    '[class*="share"],[id*="share"],[class*="social"],[id*="social"],'
    'footer,[class*="footer"],[id*="footer"]'
    '{display:none!important}'
    '</style>'
    f'<script>var __PXY_BASE="{PROXY_HOST}/proxy?url=";var __PXY_BASE_ALT="{PROXY_HOST_ALT}/proxy?url=";'
    'window.open=function(){return null;};'
    '(function(){'
    'var AD_IFRAME=/doubleclick|googlesyndication|aclib|histats|chatango|adservice|popcash|adnxs|taboola|outbrain|adroll/i;'
    'function absUrl(u){try{return new URL(u,window.location.href).href;}catch(e){return "";}}'
    'function proxyIframe(el){'
    'var raw=el.getAttribute("src")||"";if(!raw)return;'
    'if(raw.indexOf("/proxy?url=")===0||raw.indexOf(__PXY_BASE)===0||raw.indexOf(__PXY_BASE_ALT)===0){'
    'if(AD_IFRAME.test(raw)){el.style.setProperty("display","none","important");el.src="about:blank";}return;'
    '}'
    'if(/^(about:|javascript:|data:|blob:)/i.test(raw))return;'
    'var abs=absUrl(raw);if(!abs)return;'
    'if(abs.indexOf(__PXY_BASE)===0||abs.indexOf(__PXY_BASE_ALT)===0)return;'
    'if(AD_IFRAME.test(abs)){el.style.setProperty("display","none","important");el.src="about:blank";return;}'
    'if(/^https?:/i.test(abs)){el.setAttribute("src",__PXY_BASE+encodeURIComponent(abs));}'
    '}'
    'function setMediaMute(muted){'
    'document.querySelectorAll("video,audio").forEach(function(m){'
    'try{m.muted=!!muted;if(!muted)m.volume=1;}catch(e){}'
    '});'
    '}'
    'function clickUnmute(){document.querySelectorAll("button,div,span,a,input").forEach(function(el){var t=((el.textContent||el.value||el.getAttribute("aria-label")||"")+"").replace(/\\s+/g," ").trim().toUpperCase();if(/UNMUTE|SOUND ON|TURN ON SOUND|ENABLE SOUND|AUDIO ON|CLICK HERE TO UNMUTE/.test(t)){try{el.click();}catch(e){}}});}'
    'function fanoutControl(cmd){document.querySelectorAll("iframe").forEach(function(fr){try{if(fr.offsetWidth>100&&fr.offsetHeight>100){if(fr&&fr.contentWindow){fr.contentWindow.postMessage({__LOCAL_PROXY_CTRL__:cmd},"*");}}}catch(e){}});}'
    'function sweep(){'
    'document.querySelectorAll("iframe").forEach(function(f){'
    'proxyIframe(f);'
    'var raw=(f.getAttribute("src")||"");'
    'if(AD_IFRAME.test(raw)){'
    'f.style.setProperty("display","none","important");f.src="about:blank";'
    'var p=f.parentElement;var st=0;'
    'while(p&&p!==document.body&&st<4){'
    'if(p.offsetWidth>0&&p.offsetWidth<window.innerWidth*0.55)'
    '{p.style.setProperty("display","none","important");}p=p.parentElement;st++;}'
    '}'
    '});'
    'var f=document.getElementById("floated");if(f)f.style.display="none";'
    'document.querySelectorAll(".col-span-3,.col-md-3,.col-lg-3,aside,[id*=cid00200],[class*=chatango],[id*=chatango],[class*=chat-box],[id*=chat-box]").forEach(function(e){e.style.setProperty("display","none","important");});'
    '}'
    'function unmute(){setMediaMute(false);clickUnmute();fanoutControl("unmute");try{if(window.player){if(typeof window.player.unMute==="function")window.player.unMute();if(typeof window.player.unmute==="function")window.player.unmute();if(typeof window.player.setVolume==="function")window.player.setVolume(100);if("muted" in window.player)window.player.muted=false;}}catch(e){}}'
    'window.addEventListener("message",function(ev){var d=ev&&ev.data;if(!d||typeof d!=="object")return;if(d.__LOCAL_PROXY_CTRL__==="unmute"){unmute();}if(d.__LOCAL_PROXY_CTRL__==="mute"){setMediaMute(true);fanoutControl("mute");}if(d.__LOCAL_PROXY_CTRL__==="fsvid"){var vids=document.querySelectorAll("video");if(vids.length>0){document.documentElement.style.cssText="background:#000!important";document.body.style.cssText="margin:0!important;padding:0!important;background:#000!important;overflow:hidden!important";vids.forEach(function(v){v.style.cssText="position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;z-index:99999!important;object-fit:contain!important";});return;}var _skipPat=/chatango|cbox\.ws|doubleclick|googlesyndication|adzilla|adnxs|taboola|outbrain|popcash|chat\.js/i;var biggest=null,bigArea=0,videoFr=null;document.querySelectorAll("iframe").forEach(function(f){var s=(f.src||f.getAttribute("src")||"");if(_skipPat.test(s))return;try{if(!videoFr&&f.contentDocument&&f.contentDocument.querySelectorAll("video").length>0)videoFr=f;}catch(e){}var a=f.offsetWidth*f.offsetHeight;if(a>bigArea){bigArea=a;biggest=f;}});var pf=videoFr||biggest;if(!pf||bigArea===0){setTimeout(function(){window.postMessage({__LOCAL_PROXY_CTRL__:"fsvid"},"*");},700);return;}var el=pf;while(el&&el.parentElement&&el.parentElement!==document.documentElement){var par=el.parentElement;Array.from(par.children).forEach(function(ch){if(ch!==el)ch.style.setProperty("display","none","important");});el=par;}document.documentElement.style.setProperty("background","#000","important");document.body.style.setProperty("background","#000","important");document.body.style.setProperty("margin","0","important");document.body.style.setProperty("overflow","hidden","important");pf.style.cssText="position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;z-index:99999!important;border:none!important;display:block!important";document.querySelectorAll("iframe").forEach(function(f){try{f.contentWindow.postMessage({__LOCAL_PROXY_CTRL__:"fsvid"},"*");}catch(e){}});}});'
    'document.addEventListener("click",function(){unmute();},true);'
    'document.addEventListener("DOMContentLoaded",function(){sweep();unmute();});'
    'function _sendDbl(){try{window.top.postMessage({__LOCAL_PROXY_CTRL__:"dblclick"},"*");}catch(ex){}}'
    'document.addEventListener("dblclick",_sendDbl,true);'
    'window.addEventListener("dblclick",_sendDbl,true);'
    'setTimeout(unmute,300);setTimeout(unmute,1000);setTimeout(unmute,2400);setTimeout(unmute,5000);setTimeout(unmute,9000);'
    'setInterval(sweep,1500);'
    'var mo=new MutationObserver(function(){sweep();});mo.observe(document.documentElement,{childList:true,subtree:true});'
    '})();'
    '</script>'
)

# Regex patterns for frame-busting code we neutralise server-side
_FRAME_BUST = re.compile(
  r'if\s*\(\s*(?:'
  r'window\s*!==?\s*(?:window\s*\.)?\s*(?:top|parent)'
  r'|(?:window\s*\.)?\s*(?:top|parent)\s*!==?\s*window'
  r'|self\s*!==?\s*top'
  r'|top\s*!==?\s*self'
  r')\s*\)',
  re.IGNORECASE)

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_and_clean(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': base,
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return None

    # Strip <script src="ad-domain"> tags
    html = re.sub(
        r'<script[^>]+src=["\'][^"\']*(?:' + _AD_PAT + r')[^"\']*["\'][^>]*>\s*</script>',
        '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(
        r'<script[^>]+src=["\'][^"\']*(?:' + _AD_PAT + r')[^"\']*["\'][^>]*/?>',
        '', html, flags=re.IGNORECASE)
    # Strip <iframe src="ad-domain"> tags
    html = re.sub(
        r'<iframe[^>]+src=["\'][^"\']*(?:' + _AD_PAT + r')[^"\']*["\'][^>]*>.*?</iframe>',
        '', html, flags=re.DOTALL | re.IGNORECASE)

    # Rewrite root-relative URLs to absolute
    html = re.sub(
        r'(src|href|action)=(["\'])/(?!/)',
        lambda m: f'{m.group(1)}={m.group(2)}{base}/',
        html)

    # Route embedded iframes through our proxy so we can inject into them too
    def _proxy_iframe(m):
        tag = m.group(0)
        src_match = re.search(r'src=(["\'])([^"\']+)\1', tag, flags=re.IGNORECASE)
        if not src_match:
            return tag
        src = src_match.group(2).strip()
        if src.startswith(('about:', 'javascript:', 'data:', 'blob:')):
            return tag
        if src.startswith('/proxy?url='):
            return tag
        if src.startswith(f'{PROXY_HOST}/proxy?url=') or src.startswith(f'{PROXY_HOST_ALT}/proxy?url='):
            return tag

        if src.startswith('//'):
            abs_src = f'{parsed.scheme}:{src}'
        else:
            abs_src = urllib.parse.urljoin(url, src)

        abs_parsed = urllib.parse.urlparse(abs_src)
        if abs_parsed.path == '/proxy' and abs_parsed.netloc in (
            f'127.0.0.1:{PORT}', f'localhost:{PORT}'
        ) and 'url=' in (abs_parsed.query or ''):
            return tag

        if abs_src.startswith(('http://', 'https://')):
            new_src = f'{PROXY_HOST}/proxy?url=' + urllib.parse.quote(abs_src, safe='')
            tag = tag[:src_match.start()] + f'src="{new_src}"' + tag[src_match.end():]

        if 'allow=' not in tag.lower():
            tag = tag.replace('<iframe', '<iframe allow="autoplay; fullscreen"', 1)

        return tag
    html = re.sub(r'<iframe[^>]+>', _proxy_iframe, html, flags=re.IGNORECASE)

    # Strip aclib pop-up scripts
    html = re.sub(r'<script[^>]*src=["\'][^"\']*aclib[^"\']*["\'][^>]*>\s*</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<script[^>]*>\s*aclib\.runPop\([^)]*\);\s*</script>', '', html, flags=re.IGNORECASE)
    # Strip Chatango scripts
    html = re.sub(r'<script[^>]+src=["\'][^"\']*chatango[^"\']*["\'][^>]*>\s*</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<script[^>]+src=["\'][^"\']*chatango[^"\']*["\'][^>]*/>', '', html, flags=re.IGNORECASE)
    # Strip cbox chat scripts
    html = re.sub(r'<script[^>]+src=["\'][^"\']*cbox\.ws[^"\']*["\'][^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    # Neutralise frame-busting: if(window!=top){ … }
    html = _FRAME_BUST.sub('if(false)', html)
    # Strip beforeunload hijack
    html = re.sub(r"<script[^>]*>\s*window\.addEventListener\('beforeunload'.*?</script>", '', html, flags=re.DOTALL | re.IGNORECASE)
    # Strip the top-frame redirect: if(window==window.top)
    html = re.sub(r'<script>\s*if\s*\(\s*window\s*==\s*window\.top\s*\).*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Force common player configs away from muted startup
    html = re.sub(r'\bmuted\s*:\s*(?:[a-zA-Z0-9_$\(\)\s?:]+true|true)\b', 'muted:false', html, flags=re.IGNORECASE)
    html = re.sub(r'\bmute\s*:\s*(?:[a-zA-Z0-9_$\(\)\s?:]+true|true)\b', 'mute:false', html, flags=re.IGNORECASE)
    html = re.sub(r'\bvolume\s*:\s*0\b', 'volume:100', html, flags=re.IGNORECASE)
    html = re.sub(r'\bdefaultMuted\s*=\s*true\b', 'defaultMuted=false', html, flags=re.IGNORECASE)

    # For dadocric.st wrapper pages: strip chatango init scripts and containers server-side
    host = (parsed.netloc or '').lower()
    if 'dadocric.st' in host:
        # Strip any inline <script> that references chatango
        html = re.sub(r'<script[^>]*>[^<]*chatango[^<]*</script>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<script[^>]*>.*?chatango.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Neutralise cid00200 chatango embed containers (replace opening tag → hidden)
        html = re.sub(r'<div([^>]*)id="cid00200([^"]*)"', r'<div\1id="cid00200\2" style="display:none!important"', html, flags=re.IGNORECASE)
        # Neutralise any <div class="...col-span-3..."> right-column container
        html = re.sub(r'(<div[^>]*class="[^"]*\bcol-span-3\b[^"]*")', r'\1 style="display:none!important"', html, flags=re.IGNORECASE)

    # Use a lighter injector for fragile cricket player hosts to avoid breaking playback
    use_light = any(x in host for x in ('dadocric.st', 'playerado.top', 'player0003.com'))
    injector = _INJECT_LIGHT if use_light else _INJECT

    # Inject ad-blocking CSS + popup blocker
    if '</head>' in html:
      html = html.replace('</head>', injector + '</head>', 1)
    else:
      html = injector + html
    return html


def resolve_webplay_url(channel_url):
    parsed = urllib.parse.urlparse(channel_url)
    channel_id = parse_qs(parsed.query).get("id", [None])[0]
    if not channel_id:
        return channel_url

    embed_url = f"https://playerado.top/embed2.php?id={urllib.parse.quote(channel_id, safe='')}"
    req = urllib.request.Request(embed_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://playerado.top/',
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return channel_url

    fid = re.search(r'fid\s*=\s*"([^"]+)"', html)
    v_con = re.search(r'v_con\s*=\s*"([^"]+)"', html)
    v_dt = re.search(r'v_dt\s*=\s*"([^"]+)"', html)
    if not (fid and v_con and v_dt):
        return channel_url

    return (
        "https://player0003.com/atplay.php?v="
        + urllib.parse.quote(fid.group(1), safe='')
        + "&hello=" + urllib.parse.quote(v_con.group(1), safe='')
        + "&expires=" + urllib.parse.quote(v_dt.group(1), safe='')
    )


def build_html() -> str:
    channels_json = json.dumps(CHANNELS)

    sidebar_items = ""
    prev_type = None
    for key, ch in CHANNELS.items():
        if ch["type"] == "web" and prev_type != "web":
            sidebar_items += '<div class="section-label">Cricket Web Players</div>'
        elif ch["type"] == "hls" and prev_type != "hls":
            sidebar_items += '<div class="section-label">Star Sports (Live HLS)</div>'
        prev_type = ch["type"]
        badge     = "WEB" if ch["type"] == "web" else "HLS"
        badge_cls = "badge-web" if ch["type"] == "web" else "badge-hls"
        sidebar_items += f'''
        <div class="ch-item" data-id="{key}" onclick="selectChannel('{key}')">
          <span class="badge {badge_cls}">{badge}</span>
          <span class="ch-name">{ch["name"]}</span>
        </div>'''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>IPL Live Streaming</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; background: #0b0b0b; color: #f0f0f0;
                  font-family: 'Segoe UI', sans-serif; overflow: hidden; }}
    .app {{ display: flex; height: 100vh; }}

    .sidebar {{
      width: 255px; min-width: 255px; background: #111;
      border-right: 1px solid #222; display: flex; flex-direction: column; overflow: hidden;
    }}
    .sidebar-header {{
      padding: 14px 14px 10px; font-size: 1.05rem; font-weight: 700;
      color: #f5a623; border-bottom: 1px solid #222; letter-spacing: 0.4px;
    }}
    .sidebar-header span {{ font-size: 0.73rem; color: #666; display: block; font-weight: 400; margin-top: 2px; }}
    .ch-list {{ overflow-y: auto; flex: 1; padding: 4px 0; }}
    .ch-list::-webkit-scrollbar {{ width: 4px; }}
    .ch-list::-webkit-scrollbar-thumb {{ background: #2a2a2a; border-radius: 2px; }}
    .section-label {{
      font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px;
      color: #555; padding: 10px 14px 3px;
    }}
    .ch-item {{
      display: flex; align-items: center; gap: 8px;
      padding: 9px 14px; cursor: pointer; transition: background 0.1s;
      border-left: 3px solid transparent;
    }}
    .ch-item:hover {{ background: #1a1a1a; }}
    .ch-item.active {{ background: #1e1e1e; border-left-color: #f5a623; }}
    .ch-name {{ font-size: 0.83rem; }}
    .badge {{ font-size: 0.58rem; font-weight: 700; padding: 2px 5px; border-radius: 3px; flex-shrink: 0; }}
    .badge-web {{ background: #1a3d1a; color: #5cba5c; }}
    .badge-hls {{ background: #3d2200; color: #f5a623; }}

    .player-area {{ flex: 1; display: flex; flex-direction: column; background: #0b0b0b; }}
    .player-bar {{
      padding: 9px 16px; background: #111; border-bottom: 1px solid #222;
      font-size: 0.88rem; display: flex; align-items: center; gap: 10px; justify-content: space-between;
    }}
    #now-playing {{ color: #f5a623; font-weight: 600; display: inline-block; margin-right: auto; }}
    

    #player-wrap {{
      flex: 1; display: flex; align-items: center; justify-content: center;
      background: #000; position: relative; width: 100%; height: 100%;
      overflow: hidden;
    }}
    
    #hlsvid {{
      width: 100%; height: 100%; display: none; background: #000;
    }}
    
    /* Safebox iframe styles */
    #iframe-box {{
        width: 100%; height: 100%; display: none; position: relative; overflow: hidden;
    }}
    #iframe-box iframe {{
        width: 100%; height: 100%; border: none;
    }}
    

    .placeholder {{ text-align: center; color: #444; }}
    .placeholder svg {{ width: 56px; height: 56px; margin-bottom: 10px; opacity: 0.35; }}
    .placeholder p {{ font-size: 0.95rem; }}

    #err-box {{
      display: none; flex-direction: column; align-items: center; gap: 10px; text-align: center;
    }}
    #err-box p {{ color: #f88; font-size: 0.88rem; max-width: 420px; }}

    #close-btn {{
      position: absolute; top: 12px; right: 12px; z-index: 20;
      width: 44px; height: 44px; border-radius: 50%;
      background: rgba(20,20,20,0.82); border: 2px solid rgba(255,255,255,0.2);
      color: #fff; font-size: 1.2rem; cursor: pointer;
      display: none; align-items: center; justify-content: center;
      transition: background 0.2s;
    }}
    #close-btn:hover {{ background: rgba(180,30,30,0.92); }}
    #vol-btn {{
      position: absolute; bottom: 14px; right: 14px; z-index: 20;
      width: 44px; height: 44px; border-radius: 50%;
      background: rgba(20,20,20,0.82); border: 2px solid rgba(255,255,255,0.2);
      color: #fff; font-size: 1.3rem; cursor: pointer;
      display: none; align-items: center; justify-content: center;
      transition: background 0.2s;
    }}
    #vol-btn:hover {{ background: rgba(60,60,60,0.95); }}
    #fullscreen-btn {{
      position: absolute; bottom: 14px; left: 14px; z-index: 20;
      width: 44px; height: 44px; border-radius: 50%;
      background: rgba(20,20,20,0.82); border: 2px solid rgba(255,255,255,0.2);
      color: #fff; font-size: 1.3rem; cursor: pointer;
      display: none; align-items: center; justify-content: center;
      transition: background 0.2s;
    }}
    #fullscreen-btn:hover {{ background: rgba(245,166,35,0.5); }}
    #fs-btn {{
      background: #f5a623; border: none; color: #000;
      padding: 6px 14px; border-radius: 4px; cursor: pointer;
      font-size: 0.85rem; font-weight: 700; flex-shrink: 0;
    }}
    #fs-btn:hover {{ background: #ffba42; }}

    /* CSS fullscreen overlay */
    #fs-overlay {{
      display: none;
      position: fixed;
      top: 0; left: 0;
      width: 100vw; height: 100vh;
      z-index: 999999;
      background: #000;
    }}
    #fs-overlay iframe {{
      width: 100%; height: 100%; border: none;
    }}
    #fs-overlay video {{
      width: 100%; height: 100%; background: #000;
    }}
    #fs-exit-btn {{
      position: fixed;
      top: 12px; right: 12px;
      z-index: 9999999;
      width: 44px; height: 44px; border-radius: 50%;
      background: rgba(20,20,20,0.85); border: 2px solid rgba(255,255,255,0.3);
      color: #fff; font-size: 1.3rem; cursor: pointer;
      display: none; align-items: center; justify-content: center;
    }}
    #fs-exit-btn:hover {{ background: rgba(180,30,30,0.9); }}
  </style>
</head>
<body>
<script>
  // Strictly override window.open globally in the top parent
  window.open = function() {{ console.log('Blocked pop-up'); return null; }};
</script>
<div class="app">
  <div class="sidebar">
    <div class="sidebar-header">
      IPL Streaming
      <span>Secured Anti-Ad Player</span>
    </div>
    <div class="ch-list">{sidebar_items}</div>
  </div>

  <div class="player-area">
    <div class="player-bar">
      <span>Now playing: <span id="now-playing">--</span></span>
      <button id="fs-btn" onclick="toggleFullscreen()" title="Toggle fullscreen">⛶ Fullscreen</button>
    </div>
    <div id="player-wrap">
      <button id="close-btn" onclick="closePlayer()" title="Close channel">&#x2715;</button>
      <button id="vol-btn" onclick="toggleMute()" title="Toggle mute">🔇</button>
      <button id="fullscreen-btn" onclick="toggleFullscreen()" title="Toggle fullscreen">⛶</button>
      <div id="placeholder" class="placeholder">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <polygon points="10,8 16,12 10,16" fill="currentColor" stroke="none"/>
        </svg>
        <p>Choose a channel from the sidebar</p>
      </div>
      
      <!-- HLS Video Player -->
      <video id="hlsvid" controls autoplay playsinline></video>
      
      <!-- Secure IFrame Area -->
      <div id="iframe-box">
          <iframe id="vid-frame" src=""
            sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock allow-fullscreen"
            allow="autoplay; fullscreen"
            allowfullscreen>
          </iframe>
      </div>

      <div id="err-box"><p id="err-txt"></p></div>
    </div>
  </div>
</div>

<!-- Fullscreen overlay — renders completely outside the app layout -->
<div id="fs-overlay"></div>
<button id="fs-exit-btn" onclick="exitFsOverlay()" title="Exit fullscreen">&#x2715;</button>

<script>
  const CHANNELS = {channels_json};
  let hlsInstance = null;
  let isMuted = true;

  function sendFrameControl(cmd) {{
    const iframe = document.getElementById('vid-frame');
    if (iframe && iframe.contentWindow) {{
      try {{ iframe.contentWindow.postMessage({{ __LOCAL_PROXY_CTRL__: cmd }}, '*'); }} catch(e) {{}}
    }}
  }}

  document.addEventListener('click', function(ev) {{
    if (ev.target.id === 'vol-btn' || ev.target.id === 'close-btn' || ev.target.closest('.sidebar')) return;
    const inWebMode = document.getElementById('iframe-box').style.display === 'block';
    if (inWebMode && isMuted) {{
      toggleMute();
    }}
  }}, true);

  function setView(which) {{
    document.getElementById('placeholder').style.display = which === 'placeholder' ? 'flex' : 'none';
    document.getElementById('hlsvid').style.display      = which === 'video'       ? 'block': 'none';
    document.getElementById('iframe-box').style.display  = which === 'iframe'      ? 'block': 'none';
    document.getElementById('err-box').style.display     = which === 'error'       ? 'flex' : 'none';
    
    document.getElementById('close-btn').style.display       = (which !== 'placeholder') ? 'flex' : 'none';
    document.getElementById('vol-btn').style.display         = (which === 'iframe' || which === 'video') ? 'flex' : 'none';
    document.getElementById('fullscreen-btn').style.display  = (which === 'iframe' || which === 'video') ? 'flex' : 'none';
    // fs-btn is always visible — no change needed
  }}

  function destroyAll() {{
    if (hlsInstance) {{ hlsInstance.destroy(); hlsInstance = null; }}
    const v = document.getElementById('hlsvid');
    v.pause(); v.removeAttribute('src'); v.load();
    
    const ibox = document.getElementById('iframe-box');
    ibox.innerHTML = '';
    const newFr = document.createElement('iframe');
    newFr.id = 'vid-frame';
    newFr.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-pointer-lock allow-fullscreen');
    newFr.setAttribute('allow', 'autoplay; fullscreen');
    newFr.setAttribute('allowfullscreen', '');
    ibox.appendChild(newFr);

    isMuted = true;
    document.getElementById('vol-btn').textContent = '🔇';
  }}
  

  function closePlayer() {{
    destroyAll();
    setView('placeholder');
    document.getElementById('now-playing').textContent = '--';
    document.querySelectorAll('.ch-item').forEach(el => el.classList.remove('active'));
  }}

  function toggleMute() {{
    isMuted = !isMuted;
    const btn = document.getElementById('vol-btn');
    const iframe = document.getElementById('vid-frame');
    const hlsvid = document.getElementById('hlsvid');
    if (!isMuted) {{
      btn.textContent = '🔊';
      hlsvid.muted = false; hlsvid.volume = 1;
      sendFrameControl('unmute');
      try {{ iframe.contentDocument.querySelectorAll('video,audio').forEach(m => {{ m.muted=false; m.volume=1; }}); }} catch(e) {{}}
    }} else {{
      btn.textContent = '🔇';
      hlsvid.muted = true;
      sendFrameControl('mute');
      try {{ iframe.contentDocument.querySelectorAll('video,audio').forEach(m => {{ m.muted=true; }}); }} catch(e) {{}}
    }}
  }}

  var _fsActive = false;

  // Aggressively hide all chrome in a frame, leaving only the video/player iframe.
  // Uses el.contains() to identify ancestors so nothing gets missed.
  function _deepExpand(frame, depth) {{
    if (!frame || depth > 6) return;
    try {{
      var d = frame.contentDocument;
      if (!d || !d.body) return;
      var SKIP = /chatango|cbox\.ws|doubleclick|googlesyndication|adnxs|taboola|outbrain|popcash/i;

      // Case A: this frame has a <video> — make it fill the viewport
      var vids = Array.from(d.querySelectorAll('video'));
      if (vids.length > 0) {{
        var ps = d.getElementById('__fse_s__'); if (ps) ps.remove();
        var s = d.createElement('style'); s.id = '__fse_s__';
        s.textContent = 'html,body{{margin:0!important;padding:0!important;'
          + 'overflow:hidden!important;background:#000!important}}'
          + 'video{{position:fixed!important;top:0!important;left:0!important;'
          + 'width:100vw!important;height:100vh!important;'
          + 'z-index:2147483647!important;object-fit:contain!important;background:#000!important}}';
        (d.head || d.documentElement).appendChild(s);
        // Also hide every non-video, non-ancestor element
        d.querySelectorAll('body *').forEach(function(el) {{
          var tag = (el.tagName || '').toUpperCase();
          if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'VIDEO') return;
          var isAnc = vids.some(function(v) {{ return el.contains ? el.contains(v) : false; }});
          if (!isAnc) el.style.setProperty('display', 'none', 'important');
        }});
        return;
      }}

      // Case B: find the player iframe (prefer the one containing video; else largest)
      var iframes = Array.from(d.querySelectorAll('iframe'));
      var pf = null, maxArea = 0;
      iframes.forEach(function(f) {{
        if (SKIP.test(f.src || f.getAttribute('src') || '')) return;
        // Prefer iframe that contains a <video>
        try {{
          if (f.contentDocument && f.contentDocument.querySelectorAll('video').length > 0) {{
            pf = f; maxArea = Infinity; return;
          }}
        }} catch(e2) {{}}
        if (maxArea !== Infinity) {{
          var a = f.offsetWidth * f.offsetHeight;
          if (a > maxArea) {{ maxArea = a; pf = f; }}
        }}
      }});

      if (!pf) {{
        // No visible iframe yet — retry after the page finishes rendering
        setTimeout(function() {{ _deepExpand(frame, depth); }}, 700);
        return;
      }}

      // Blacken background
      d.documentElement.style.setProperty('background', '#000', 'important');
      d.body.style.setProperty('background', '#000', 'important');
      d.body.style.setProperty('overflow', 'hidden', 'important');
      d.body.style.setProperty('margin', '0', 'important');

      // Hide EVERY body element that is not pf and not an ancestor of pf
      d.querySelectorAll('body *').forEach(function(el) {{
        var tag = (el.tagName || '').toUpperCase();
        if (tag === 'SCRIPT' || tag === 'STYLE') return;
        if (el === pf) return;
        var isAnc = el.contains ? el.contains(pf) : false;
        if (!isAnc) {{
          if (!el.hasAttribute('data-fse-h')) el.setAttribute('data-fse-h', el.style.cssText || '');
          el.style.setProperty('display', 'none', 'important');
        }}
      }});

      // Make pf fill the full viewport
      if (!pf.hasAttribute('data-fse-p')) pf.setAttribute('data-fse-p', pf.style.cssText || '');
      pf.style.setProperty('position', 'fixed', 'important');
      pf.style.setProperty('top', '0', 'important');
      pf.style.setProperty('left', '0', 'important');
      pf.style.setProperty('width', '100vw', 'important');
      pf.style.setProperty('height', '100vh', 'important');
      pf.style.setProperty('z-index', '2147483647', 'important');
      pf.style.setProperty('border', 'none', 'important');
      pf.style.setProperty('display', 'block', 'important');

      // Recurse into pf to expand the video inside it
      _deepExpand(pf, depth + 1);
    }} catch(e) {{}}
  }}

  function _deepCleanup(frame, depth) {{
    if (!frame || depth > 6) return;
    try {{
      var d = frame.contentDocument;
      if (!d) return;
      var s = d.getElementById('__fse_s__'); if (s) s.remove();
      d.querySelectorAll('[data-fse-h]').forEach(function(el) {{
        el.style.cssText = el.getAttribute('data-fse-h') || '';
        el.removeAttribute('data-fse-h');
      }});
      d.querySelectorAll('[data-fse-p]').forEach(function(el) {{
        el.style.cssText = el.getAttribute('data-fse-p') || '';
        el.removeAttribute('data-fse-p');
      }});
      d.documentElement.style.removeProperty('background');
      d.body.style.cssText = '';
      d.querySelectorAll('iframe').forEach(function(f) {{ _deepCleanup(f, depth + 1); }});
    }} catch(e) {{}}
  }}

  function enterFsOverlay() {{
    if (_fsActive) return;
    _fsActive = true;
    const ibox   = document.getElementById('iframe-box');
    const fr     = document.getElementById('vid-frame');
    const hlsvid = document.getElementById('hlsvid');
    const iframeMode = ibox.style.display === 'block';

    document.getElementById('fs-exit-btn').style.display = 'flex';
    document.getElementById('fs-btn').textContent = '⛶ Exit FS';

    if (iframeMode) {{
      // Stretch ibox to cover full viewport — no reload, video keeps playing
      ibox._fsOrig = ibox.style.cssText;
      ibox.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;'
        + 'z-index:999999;background:#000;display:block;border:none';
      // Aggressively hide chrome inside the frame tree
      _deepExpand(fr, 0);
      setTimeout(function() {{ _deepExpand(fr, 0); }}, 700);
      // Also fan out fsvid for any frame that has its own handler
      try {{ fr.contentWindow.postMessage({{__LOCAL_PROXY_CTRL__:'fsvid'}}, '*'); }} catch(e) {{}}
      setTimeout(function() {{
        try {{ fr.contentWindow.postMessage({{__LOCAL_PROXY_CTRL__:'fsvid'}}, '*'); }} catch(e) {{}}
      }}, 800);
      try {{ ibox.requestFullscreen(); }} catch(e) {{}}
    }} else {{
      // HLS mode — clone stream into overlay video element
      const overlay = document.getElementById('fs-overlay');
      overlay.innerHTML = '';
      var fsVid = document.createElement('video');
      fsVid.src = hlsvid.src; fsVid.controls = true;
      fsVid.autoplay = true; fsVid.muted = hlsvid.muted;
      fsVid.style.cssText = 'width:100%;height:100%;background:#000';
      overlay.appendChild(fsVid);
      overlay.style.display = 'block';
      try {{ overlay.requestFullscreen(); }} catch(e) {{}}
    }}
  }}

  function exitFsOverlay() {{
    if (!_fsActive) return;
    _fsActive = false;
    const ibox  = document.getElementById('iframe-box');
    const fr    = document.getElementById('vid-frame');
    const overlay = document.getElementById('fs-overlay');

    if (ibox._fsOrig !== undefined) {{
      ibox.style.cssText = ibox._fsOrig;
      delete ibox._fsOrig;
    }}
    _deepCleanup(fr, 0);

    overlay.style.display = 'none';
    overlay.innerHTML = '';
    document.getElementById('fs-exit-btn').style.display = 'none';
    document.getElementById('fs-btn').textContent = '⛶ Fullscreen';
    try {{ document.exitFullscreen(); }} catch(e) {{}}
  }}

  function toggleFullscreen() {{
    if (_fsActive) {{ exitFsOverlay(); }} else {{ enterFsOverlay(); }}
  }}

  document.addEventListener('fullscreenchange', function() {{
    if (!document.fullscreenElement && _fsActive) exitFsOverlay();
  }});

  document.addEventListener('keydown', function(ev) {{
    if (ev.key === 'Escape') exitFsOverlay();
    if ((ev.key === 'f' || ev.key === 'F') && !ev.ctrlKey) toggleFullscreen();
  }});

  document.getElementById('hlsvid').addEventListener('dblclick', function() {{
    toggleFullscreen();
  }});

  window.addEventListener('message', function(ev) {{
    var d = ev && ev.data;
    if (!d || typeof d !== 'object') return;
    if (d.__LOCAL_PROXY_CTRL__ === 'dblclick') toggleFullscreen();
  }});

  function selectChannel(id) {{
    const ch = CHANNELS[id];
    if (!ch) return;

    document.querySelectorAll('.ch-item').forEach(el => el.classList.remove('active'));
    const item = document.querySelector('.ch-item[data-id="' + id + '"]');
    if (item) item.classList.add('active');
    document.getElementById('now-playing').textContent = ch.name;

    destroyAll();

    if (ch.type === 'hls') {{
      setView('video');
      const video = document.getElementById('hlsvid');

      video.muted = true;
      video.volume = 0;
      isMuted = true;
      document.getElementById('vol-btn').textContent = '🔇';
      if (Hls.isSupported()) {{
        hlsInstance = new Hls({{ enableWorker: true, lowLatencyMode: true }});
        hlsInstance.loadSource(ch.url);
        hlsInstance.attachMedia(video);
        hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {{ video.muted = isMuted; video.play(); }});
        hlsInstance.on(Hls.Events.ERROR, (_, data) => {{
          if (data.fatal) {{
            setView('error');
            document.getElementById('err-txt').textContent = 'Stream error. The stream may be offline or geo-restricted.';
          }}
        }});
      }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
        video.src = ch.url;
        video.play();
      }} else {{
        setView('error');
        document.getElementById('err-txt').textContent = 'HLS not supported. Please use Chrome or Edge.';
      }}
    }} else if (ch.type === 'web') {{
      setView('iframe');
      isMuted = true;
      document.getElementById('vol-btn').textContent = '🔇';
      const _fr = document.getElementById('vid-frame');
      _fr.onload = function() {{
        setTimeout(function(){{ sendFrameControl(isMuted ? 'mute' : 'unmute'); }}, 250);
        setTimeout(function(){{ sendFrameControl(isMuted ? 'mute' : 'unmute'); }}, 1200);
        setTimeout(function(){{ sendFrameControl(isMuted ? 'mute' : 'unmute'); }}, 2800);
        try {{
          const _d = _fr.contentDocument;
          const _AD = /1win|adzilla|casino|superbonus|geographicalpaperworkmovie|aclib|histats/i;
          // Auto-click and hide UNLOCK button and overlay elements
          _d.querySelectorAll('button,div,span,a').forEach(function(el) {{
            var txt = (el.textContent||'').toUpperCase().trim();
            if (txt.indexOf('UNMUTE')>-1) {{
              try{{el.click();}}catch(e){{}}
            }} else if (txt.indexOf('UNLOCK')>-1 || txt.indexOf('CLICK (3S)')>-1 || txt==='CLICK') {{
              try{{el.click();}}catch(e){{}}
              el.style.display='none';
            }}
          }});
          // Hide floated ad div
          var f=_d.getElementById('floated'); if(f) f.style.display='none';
          // Hide header/nav/footer
          _d.querySelectorAll('header,nav,footer').forEach(function(e){{e.style.display='none';}});
          // Hide ad anchor containers
          _d.querySelectorAll('a').forEach(function(a) {{
            if (_AD.test(a.href||'') || _AD.test(a.getAttribute('data-href')||'')) {{
              let el = a;
              for (let i=0; i<8; i++) {{
                let p = el.parentElement;
                if (!p || p === _d.body) break;
                if (el.offsetWidth > 100 && el.offsetHeight > 80) {{ el.style.display='none'; break; }}
                el = p;
              }}
            }}
          }});
          // Hide chat panel & Chatango
          _d.querySelectorAll('[class*="chat"],[id*="chat"],[class*="Chat"],[id*="Chat"],[id*="cid00200"]').forEach(function(e){{e.style.display='none';}});
          // Kill known ad iframes only; keep player iframes alive
          _d.querySelectorAll('iframe').forEach(function(e){{
            var s=(e.getAttribute('src')||e.src||'');
            if(/doubleclick|googlesyndication|geographicalpaperworkmovie|aclib|histats|chatango|adservice|popcash|adnxs|taboola|outbrain/i.test(s)){{
              e.style.display='none';
              e.src='about:blank';
            }}
          }});
          // Kill ad sidebar columns
          _d.querySelectorAll('.col-span-3').forEach(function(e){{e.style.display='none';}});
          // Fix 4: hide social share bars and ad containers
          _d.querySelectorAll('[class*="share"],[id*="share"],[class*="social"],[id*="social"]').forEach(function(e){{e.style.display='none';}});
          _d.querySelectorAll('[class*="ad-"],[class*="-ad"],[id*="banner"],[class*="banner"],[class*="advertisement"],[id*="advertisement"]').forEach(function(e){{e.style.display='none';}});
        }} catch(e) {{}}

        // Fix 5: MutationObserver to auto-hide UNMUTE banner as soon as it appears
        try {{
          var _win = _fr.contentWindow || _fr.contentDocument.defaultView;
          var _moDoc = _fr.contentDocument;
          var _unmuteMo = new _win.MutationObserver(function() {{
            _moDoc.querySelectorAll('button,div,span,a,p').forEach(function(el) {{
              var t = ((el.textContent||el.value||'')+'').replace(/\\s+/g,' ').trim().toUpperCase();
              if (t.length < 60 && /UNMUTE|CLICK HERE TO UNMUTE/.test(t)) {{
                try{{ el.click(); }}catch(e){{}}
                el.style.setProperty('display','none','important');
              }}
            }});
          }});
          _unmuteMo.observe(_moDoc.documentElement, {{childList:true, subtree:true}});
          setTimeout(function(){{ _unmuteMo.disconnect(); }}, 30000);
        }} catch(e) {{}}
      }};
      _fr.src = '{PROXY_HOST}/proxy?url=' + encodeURIComponent(ch.url);
    }}
  }}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = build_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            try:
              self.wfile.write(html)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
              pass
        elif parsed.path == "/proxy":
            target = parse_qs(parsed.query).get("url", [None])[0]
            if target and any(d in target.lower() for d in ['chatango.com', 'chatango.net', 'cbox.ws']):
                blank = b'<html><body></body></html>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(blank))
                self.end_headers()
                try: self.wfile.write(blank)
                except: pass
                return
            content = fetch_and_clean(target) if target else None
            if content:
                data = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", len(data))
                self.end_headers()
                try:
                  self.wfile.write(data)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                  pass
            else:
                self.send_response(502)
                self.end_headers()
        elif parsed.path == "/webplay":
            ch_id = parse_qs(parsed.query).get("id", [None])[0]
            ch = CHANNELS.get(ch_id) if ch_id else None
            if not ch or ch.get("type") != "web":
                self.send_response(404)
                self.end_headers()
                return

            resolved = resolve_webplay_url(ch["url"])
            content = fetch_and_clean(resolved)
            if content:
                data = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", len(data))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass
            else:
                self.send_response(502)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


class ReusableHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = ReusableHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"IPL Robust Dashboard -> {url}")
    print("Press Ctrl+C to stop.\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
