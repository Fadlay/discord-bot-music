import yt_dlp

ytdl_format_options = {
    'format': 'bestaudio/best',
    'cookiesfrombrowser': ('firefox',),
    'js_runtimes': {'node': {'exe': r'C:\Program Files\nodejs\node.exe'}}
}

with yt_dlp.YoutubeDL(ytdl_format_options) as ydl:
    try:
        info = ydl.extract_info("f5-IY_Ja1RM", download=False)
        print("SUCCESS")
        print("Formats available:", len(info.get('formats', [])))
    except Exception as e:
        print("FAIL:", e)
