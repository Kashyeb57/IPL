import urllib.request
import re

def get_yt_live(query):
    req = urllib.request.Request(f'https://www.youtube.com/results?search_query={urllib.parse.quote(query)}&sp=EgJAAQ%253D%253D', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        results = []
        for match in re.finditer(r'"videoId":"([^"]+)".*?"title":{"runs":\[{"text":"([^"]+)"', html):
            results.append((match.group(1), match.group(2)))
        return list(dict.fromkeys(results))[:5]
    except Exception as e:
        return str(e)

print("\nCNN:", get_yt_live("CNN Live"))
print("\nFox:", get_yt_live("Fox News Live"))
