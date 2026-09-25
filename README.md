# mariosl Media Downloader

A simple local media downloader built with Python, Flask, yt-dlp, and FFmpeg.

## Features

* Video downloads
* Audio downloads
* MP3, WAV, and OGG audio
* Media information preview
* Download progress
* Saves downloads to the user's Windows Downloads folder
* Local web interface
* No accounts
* No tracking

## Supported Sources

The downloader is powered by yt-dlp and supports a large number of websites and services.

Some commonly supported sources include:

* YouTube
* YouTube Music
* Vimeo
* TikTok
* Instagram
* X
* Reddit
* Twitch
* Facebook
* Dailymotion
* SoundCloud
* Bandcamp
* Mixcloud
* Audiomack
* Bilibili
* VK
* Kick
* Flickr
* Imgur
* Streamable
* Vevo
* Archive.org
* Google Drive
* Dropbox
* Wistia
* Vidyard
* TED
* BBC
* CNN
* ESPN

Support ultimately depends on yt-dlp's current extractors. Websites can change their systems, which may temporarily break individual sources or require authentication.

## Downloads

Files are saved directly to the user's Windows Downloads folder.

The application detects the Windows Downloads location automatically, including redirected locations such as OneDrive.

## Windows Release

Download the latest standalone `.exe` from the GitHub Releases section.

The release includes FFmpeg, so users do not need to install FFmpeg separately.

## Running from Source

Install the dependencies listed in `requirements.txt` and make sure FFmpeg is available.

Then run:

```text
python app.py
```

The application runs locally at:

```text
http://127.0.0.1:5000
```

## Disclaimer

This project is intended for downloading media that you have permission to download. Respect the terms of service and copyright laws applicable to the content and websites you use it with.

## License

[License to be added]
