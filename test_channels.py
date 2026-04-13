import Entertainment

web_cricket = []
hls_streams = []
news_streams = []

for key, ch in Entertainment.CHANNELS.items():
    name_upper = ch['name'].upper()
    if 'NEWS' in name_upper or 'CNN' in name_upper or 'FOX' in name_upper or 'ABC' in name_upper or 'CNBC' in name_upper:
        news_streams.append((key, ch))

print('News channels found:')
for key, ch in sorted(news_streams):
    print(f'  {key}: {ch["name"]}')
