import Entertainment

html = Entertainment.build_html()

# Find News section
start = html.find('News Quota')
end = html.find('Now playing:', start)
if start != -1 and end != -1:
    section = html[start:end]
    print(section)
    print("\n--- Looking for CNBC ---")
    if 'CNBC' in section:
        print("CNBC FOUND in returned HTML")
    else:
        print("CNBC NOT FOUND in returned HTML")
