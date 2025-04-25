import os
import re
import logging
import yt_dlp
from yt_dlp.utils import DownloadError
import glob  # Make sure this is imported

# Configure logging
print("Youtube Downloader") 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_video_id(url):
    """Extracts the video ID from a YouTube URL."""
    # Handle different YouTube URL formats
    youtube_regex = (
        r'(?:youtube(?:-nocookie)?\.com/(?:[^/]+/.+/|(?:v|e(?:mbed)?)/|.*[?&]v=)|youtu\.be/)([^"&?/ ]{11})'
    )
    match = re.search(youtube_regex, url)
    return match.group(1) if match else None

def download_youtube_video(url, output_dir=None, quality='best', format='mp4'):
    """
    Downloads a YouTube video and returns the path to the downloaded file.
    
    Args:
        url (str): YouTube URL
        output_dir (str, optional): Directory to save the file. Defaults to script directory.
        quality (str, optional): Quality setting. Options: 'best', 'medium', 'worst'. Defaults to 'best'.
        format (str, optional): Output format. Defaults to 'mp4'.
        
    Returns:
        str: Path to the downloaded file, or None if download failed.
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    logging.info(f"YouTube download function called with URL: {url}")
    logging.info(f"Output directory: {output_dir}")
    
    video_id = get_video_id(url)
    if not video_id:
        logging.error("Could not extract YouTube video ID from URL.")
        return None
    
    logging.info(f"Extracted video ID: {video_id}")
    
    # Determine format based on quality
    if quality == 'best':
        format_str = f'bestvideo[ext={format}]+bestaudio[ext=m4a]/best[ext={format}]/best'
    elif quality == 'medium':
        format_str = f'bestvideo[height<=720][ext={format}]+bestaudio[ext=m4a]/best[height<=720][ext={format}]/best[height<=720]'
    elif quality == 'worst':
        format_str = f'worstvideo[ext={format}]+worstaudio[ext=m4a]/worst[ext={format}]/worst'
    else:
        format_str = f'bestvideo[ext={format}]+bestaudio[ext=m4a]/best[ext={format}]/best'
    
    # Set up output filename template
    output_template = os.path.join(output_dir, f'youtube_{video_id}.%(ext)s')
    logging.info(f"Using output template: {output_template}")
    
    # Let's use simpler options to diagnose issues
    ydl_opts = {
        'format': format_str,
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': False,  # Set to False to see all output
        'verbose': True,  # Add verbose output for debugging
        'no_warnings': False,  # Show warnings
    }
    
    logging.info(f"YoutubeDL options: {ydl_opts}")
    logging.info(f"Attempting to download YouTube video: {url}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First, extract info without downloading to make sure we can access the video
            info = ydl.extract_info(url, download=False)
            if not info:
                logging.error("Failed to extract video information.")
                return None
            
            logging.info(f"Video info extracted successfully. Title: {info.get('title')}")
            logging.info(f"Beginning actual download process...")
            
            # Now download the video
            download_info = ydl.extract_info(url, download=True)
            
            # Try to determine the output file path
            downloaded_file = None
            
            # Method 1: Check requested_downloads
            if 'requested_downloads' in download_info and download_info['requested_downloads']:
                downloaded_file = download_info['requested_downloads'][0].get('filepath')
                logging.info(f"Method 1 - File path from requested_downloads: {downloaded_file}")
            
            # Method 2: Use prepare_filename
            if not downloaded_file or not os.path.exists(downloaded_file):
                try:
                    downloaded_file = ydl.prepare_filename(download_info)
                    logging.info(f"Method 2 - File path from prepare_filename: {downloaded_file}")
                except Exception as e:
                    logging.error(f"Error using prepare_filename: {e}")
            
            # Method 3: Search for files matching pattern
            if not downloaded_file or not os.path.exists(downloaded_file):
                search_pattern = os.path.join(output_dir, f'youtube_{video_id}.*')
                logging.info(f"Method 3 - Searching for files with pattern: {search_pattern}")
                matches = glob.glob(search_pattern)
                if matches:
                    # Sort by modification time, newest first
                    matches.sort(key=os.path.getmtime, reverse=True)
                    downloaded_file = matches[0]
                    logging.info(f"Found files: {matches}")
                    logging.info(f"Selected newest file: {downloaded_file}")
            
            # Final check
            if downloaded_file and os.path.exists(downloaded_file):
                logging.info(f"YouTube video downloaded successfully to: {downloaded_file}")
                logging.info(f"File size: {os.path.getsize(downloaded_file)} bytes")
                return downloaded_file
            else:
                logging.error(f"Download seemed to succeed but file not found at expected path.")
                # List all files in the output directory as a last-ditch effort
                all_files = os.listdir(output_dir)
                logging.info(f"All files in {output_dir}: {all_files}")
                return None
    
    except DownloadError as e:
        logging.error(f"YouTube download error: {e}")
        return None
    except Exception as e:
        logging.exception(f"Unexpected error during YouTube download: {e}")
        return None

if __name__ == "__main__":
    # Test the function if run directly
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        result = download_youtube_video(url)
        print(f"Download result: {result}")
    else:
        print("Usage: python YouTube_Downloader.py <youtube_url>")
