# ftp_sync - A simple FTP/SFTP snyc script
Uses a local .env file to get the FTP/SFTP server settings and

1. Gets remote files
2. Gets local files
3. Looks for changes according to filesize
4. Mirrors directories
5. Uploads changed files
6. Deletes remote files, which are not available locally

> [!NOTE]
>  The script was written to upload the output from a static site generator to a FTP/SFTP server, thus it only compares the file size to look for changes.
