import sys
import os
import re
import yt_dlp
from yt_dlp.utils import DownloadError
from moviepy.video.io.VideoFileClip import VideoFileClip
import tempfile
import logging
import argparse
import subprocess
import shutil
import json
from PIL import Image
import requests # Added for direct image download
import glob
import time

# Add selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
TARGET_SIZE_MB = 9.2
TARGET_SIZE_BYTES = TARGET_SIZE_MB * 1024 * 1024
IMAGE_FRAME_DURATION = 500 # Milliseconds per frame in image GIF

# --- Helper Functions ---
def get_tweet_id(url):
    """Extracts the tweet ID from a Twitter URL."""
    match = re.search(r'status/(\d+)', url)
    return match.group(1) if match else None

# Refactored to use requests for image downloads and a revised fallback
def download_media(url, output_dir):
    """
    Downloads media (video or images) from the given URL.
    Attempts yt-dlp info extraction first. If only images are present,
    it extracts their URLs and downloads them using requests.
    Returns (media_type, downloaded_paths) or (None, None) on failure.
    """
    tweet_id = get_tweet_id(url)
    if not tweet_id:
        logging.error("Could not extract tweet ID from URL.")
        return None, None

    media_type = None
    downloaded_paths = []
    image_urls_to_download = []
    media_info = None
    attempt_image_fallback = False

    # --- Step 1: Info extraction ---
    info_opts = {
        'quiet': True, 'no_warnings': True,
        'dump_single_json': True, 'noplaylist': True,
    }
    logging.info(f"Fetching media info for {url}…")
    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            media_info = ydl.extract_info(url, download=False)
            if not media_info:
                 logging.error("yt-dlp extracted no info.")
                 return None, None

    except DownloadError as e:
        err = str(e).lower()
        if "no video" in err or "no media formats found" in err or "could not find tweet" in err:
            logging.warning(f"Initial info extraction failed ({e}). Will attempt image-only extraction.")
            attempt_image_fallback = True
        else:
            logging.error(f"yt-dlp error during info extraction: {e}")
            return None, None
    except Exception as e:
        logging.error(f"Unexpected info extraction error: {e}")
        return None, None

    # NEW: If info extraction did not yield useful info and URL itself ends with common image/gif ext, use it directly.
    if not media_info and url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
        logging.info(f"No usable info extracted; using input URL as image URL: {url}")
        media_type = 'image'
        image_urls_to_download = [url]
        return media_type, image_urls_to_download

    # --- Step 2: Determine type or trigger fallback ---
    if not attempt_image_fallback and media_info:
        # Check formats first for definitive video evidence
        is_video = False
        if media_info.get('formats'):
            is_video = any(f.get('vcodec', 'none') != 'none' for f in media_info['formats'])
        elif media_info.get('entries'):
             # Check entries if top-level formats are missing (less common)
             is_video = any(e.get('vcodec', 'none') != 'none' for e in media_info['entries'])
        # Check top-level vcodec as a fallback check
        elif media_info.get('vcodec', 'none') != 'none':
             is_video = True

        if is_video:
            media_type = 'video'
            logging.info("Detected video based on formats or vcodec.")
        else:
            # Assume image if no video evidence found
            media_type = 'image'
            entries = media_info.get('entries')
            if entries:
                # Extract image URLs from entries
                image_urls_to_download = [
                    e.get('url') for e in entries
                    if e.get('url') and e.get('vcodec', 'none') == 'none'
                ]
                # If no URLs found with vcodec check, try getting all entry URLs
                if not image_urls_to_download:
                     image_urls_to_download = [e.get('url') for e in entries if e.get('url')]
                logging.info(f"Detected image gallery with {len(image_urls_to_download)} images.")
            else:
                # Single item: prioritize URL if vcodec is none, else thumbnail, else URL anyway
                img_url = media_info.get('url')
                thumb_url = None
                if media_info.get('thumbnails'):
                    thumb_url = media_info['thumbnails'][-1]['url'] # Highest res

                if img_url and media_info.get('vcodec', 'none') == 'none':
                    image_urls_to_download = [img_url]
                elif thumb_url:
                    image_urls_to_download = [thumb_url]
                elif img_url: # Use URL as last resort even if vcodec wasn't 'none'
                    image_urls_to_download = [img_url]

                if image_urls_to_download:
                    logging.info(f"Detected single image URL: {image_urls_to_download[0]}")
                else:
                    # If still no URL, trigger fallback
                    logging.warning("Could not determine single image URL. Attempting fallback.")
                    attempt_image_fallback = True
                    media_type = None # Reset media_type to ensure fallback runs fully

        # If type is image but no URLs were found, trigger fallback
        if media_type == 'image' and not image_urls_to_download:
             logging.warning("Detected image type but found no URLs. Attempting fallback.")
             attempt_image_fallback = True
             media_type = None # Reset media_type

        # Final check if type couldn't be determined and not already falling back
        if not media_type and not attempt_image_fallback:
            logging.warning("Could not determine media type. Attempting fallback.")
            attempt_image_fallback = True

    # --- Step 3: Download or Fallback ---

    if media_type == 'video':
        # --- Video Download (using yt-dlp download) ---
        # Use a template yt-dlp can fill
        temp_video_path_tmpl = os.path.join(output_dir, f"temp_media_{tweet_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': temp_video_path_tmpl,
            'noplaylist': True, 'quiet': True, 'no_warnings': True,
        }
        logging.info("Attempting video download via yt-dlp...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Let ydl handle download and find the file
                res = ydl.extract_info(url, download=True)
                downloaded_file = None
                # Try finding filepath from requested_downloads (newer yt-dlp)
                if 'requested_downloads' in res and res['requested_downloads']:
                    downloaded_file = res['requested_downloads'][0].get('filepath')
                # Fallback using prepare_filename
                if not downloaded_file and res:
                    try:
                        downloaded_file = ydl.prepare_filename(res)
                    except Exception as prep_e:
                         logging.warning(f"Error calling prepare_filename: {prep_e}")

                # Check if the determined/prepared path exists
                if downloaded_file and os.path.exists(downloaded_file):
                    logging.info(f"Video downloaded successfully: {downloaded_file}")
                    downloaded_paths.append(downloaded_file)
                else:
                    # Search pattern as a final fallback if path determination failed
                    logging.warning(f"Could not confirm video path ({downloaded_file}), searching pattern...")
                    search_pattern = os.path.join(output_dir, f"temp_media_{tweet_id}.*")
                    found = [f for f in glob.glob(search_pattern) if not f.endswith(('.part', '.ytdl')) and os.path.splitext(f)[1].lower() in ['.mp4', '.mkv', '.webm']] # More specific video extensions
                    if found:
                        # Sort by size or modification time? Assume first is okay for now.
                        downloaded_paths.append(found[0])
                        logging.info(f"Found video file via pattern: {found[0]}")
                    else:
                        logging.error("yt-dlp finished for video but output file not found.")
                        return None, None
        except DownloadError as dl_e:
             # Handle cases where download fails even if info succeeded
             logging.error(f"Error during video download phase via yt-dlp: {dl_e}")
             return None, None
        except Exception as e:
            logging.error(f"Unexpected error during video download via yt-dlp: {e}")
            return None, None


    elif media_type == 'image' or attempt_image_fallback:
        # --- Image Download (using requests, potentially triggered by fallback) ---
        if attempt_image_fallback and not image_urls_to_download:
            # Fallback: Re-attempt info extraction focusing on URLs/Thumbnails
            logging.info("Fallback: Re-attempting info extraction to find image URLs...")
            fallback_info_opts = {
                'quiet': True, 'no_warnings': True,
                'dump_single_json': True, 'noplaylist': True,
                'ignoreerrors': True,
            }
            media_info_fallback = None # Reset
            try:
                with yt_dlp.YoutubeDL(fallback_info_opts) as ydl:
                    media_info_fallback = ydl.extract_info(url, download=False)

                if media_info_fallback:
                    # Try extracting URLs again with fallback info
                    entries = media_info_fallback.get('entries')
                    if entries:
                        image_urls_to_download = [e.get('url') for e in entries if e.get('url') and e.get('vcodec', 'none') == 'none']
                        if not image_urls_to_download: # If specific check fails, grab all URLs
                             image_urls_to_download = [e.get('url') for e in entries if e.get('url')]
                        logging.info(f"Fallback extracted {len(image_urls_to_download)} potential image URLs from entries.")
                    else:
                        # Single item fallback check
                        img_url = media_info_fallback.get('url')
                        thumb_url = None
                        if media_info_fallback.get('thumbnails'):
                            thumb_url = media_info_fallback['thumbnails'][-1]['url']

                        # Prioritize direct URL if vcodec is none, else thumbnail, else URL
                        if img_url and media_info_fallback.get('vcodec', 'none') == 'none':
                            image_urls_to_download = [img_url]
                        elif thumb_url:
                            image_urls_to_download = [thumb_url]
                        elif img_url:
                            image_urls_to_download = [img_url]

                        if image_urls_to_download:
                             logging.info(f"Fallback extracted image URL: {image_urls_to_download[0]}")
                else:
                    logging.warning("Fallback info extraction yielded no result.")

            except DownloadError as fallback_dl_e:
                 # Log specific DownloadError during fallback info extraction but continue
                 logging.warning(f"DownloadError during fallback info extraction (ignored): {fallback_dl_e}")
            except Exception as fallback_e:
                # Log other errors during fallback info extraction but continue
                logging.error(f"Error during fallback info extraction (ignored): {fallback_e}")
                # Proceed without URLs, will fail below if list is empty

        # --- Actual Image Download using Requests ---
        if not image_urls_to_download:
            logging.error("Could not find any image URLs to download, even after fallback.")
            return None, None

        # Set media type definitively if we got here via fallback
        if attempt_image_fallback:
            media_type = 'image'

        logging.info(f"Attempting image download via requests for {len(image_urls_to_download)} URLs...")
        # (Keep existing requests download loop)
        # ... (no changes needed in this block) ...
        for i, img_url in enumerate(image_urls_to_download):
            if not img_url:
                logging.warning(f"Skipping empty image URL at index {i}.")
                continue
            try:
                # Ensure URL has scheme
                if not img_url.startswith(('http://', 'https://')):
                    logging.warning(f"Skipping invalid URL (no scheme): {img_url}")
                    continue

                response = requests.get(img_url, stream=True, timeout=30)
                response.raise_for_status()

                content_type = response.headers.get('content-type')
                ext = '.jpg' # Default
                # Basic extension guessing
                if content_type:
                    mime_type = content_type.split(';')[0].strip()
                    if mime_type == 'image/jpeg': ext = '.jpg'
                    elif mime_type == 'image/png': ext = '.png'
                    elif mime_type == 'image/webp': ext = '.webp'
                    elif mime_type == 'image/gif': ext = '.gif'
                else: # Fallback to URL parsing
                    try:
                        path_part = requests.utils.urlparse(img_url).path
                        parsed_ext = os.path.splitext(path_part)[-1]
                        if parsed_ext and parsed_ext.lower() in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                            ext = parsed_ext.lower()
                    except Exception:
                         pass # Ignore URL parsing errors for extension

                temp_image_path = os.path.join(output_dir, f"temp_media_{tweet_id}_{i+1}{ext}")

                with open(temp_image_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                if os.path.exists(temp_image_path) and os.path.getsize(temp_image_path) > 0: # Check size > 0
                    logging.info(f"Image {i+1} downloaded successfully: {temp_image_path}")
                    downloaded_paths.append(temp_image_path)
                else:
                    logging.warning(f"Image {i+1} download finished but file not found or empty at {temp_image_path}")
                    if os.path.exists(temp_image_path): # Clean up empty file
                         try: os.remove(temp_image_path)
                         except OSError: pass


            except requests.exceptions.RequestException as e:
                logging.error(f"Error downloading image {i+1} from {img_url}: {e}")
                # Clean up potentially created file
                if 'temp_image_path' in locals() and os.path.exists(temp_image_path):
                     try: os.remove(temp_image_path)
                     except OSError: pass
                # Fail entire process if one image fails
                return None, None

        if not downloaded_paths:
             logging.error("Image download process (requests) completed, but no images were successfully saved.")
             return None, None


    else:
        logging.error("Unexpected download state. No media type determined and fallback not triggered appropriately.")
        return None, None

    # --- Final check ---
    if not downloaded_paths:
        logging.error("Download process completed, but no files were successfully saved or found.")
        return None, None

    downloaded_paths = [os.path.abspath(p) for p in downloaded_paths]
    # Ensure media_type is set if fallback succeeded
    if attempt_image_fallback and not media_type:
        media_type = 'image'

    # Final safety check: if media_type is still None, infer from downloaded files
    if not media_type and downloaded_paths:
         first_ext = os.path.splitext(downloaded_paths[0])[1].lower()
         if first_ext in ['.mp4', '.mkv', '.webm']:
              media_type = 'video'
         elif first_ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
              media_type = 'image'
         logging.warning(f"Inferred media type as '{media_type}' based on downloaded file extension.")


    if not media_type: # If still None after all checks
         logging.error("Could not determine final media type.")
         return None, None

    return media_type, downloaded_paths


# New function to convert images to GIF
def convert_images_to_gif(image_paths, gif_path):
    """Converts a list of images to an animated GIF using Pillow."""
    if not image_paths:
        logging.error("No image paths provided for GIF conversion.")
        return None

    try:
        images = [Image.open(p) for p in image_paths]
        # Ensure all images are in RGBA or RGB for consistency if needed
        # images = [img.convert("RGBA") for img in images]

        if not images:
            logging.error("Could not open any images.")
            return None

        first_image = images[0]
        subsequent_frames = images[1:]

        first_image.save(
            gif_path,
            save_all=True,
            append_images=subsequent_frames,
            duration=IMAGE_FRAME_DURATION, # Duration per frame in ms
            loop=0  # Loop forever
        )
        logging.info(f"Image GIF created successfully: {gif_path}")

        # Close images
        for img in images:
            img.close()

        return gif_path
    except Exception as e:
        logging.exception(f"Error converting images to GIF: {e}")
        # Clean up potentially partially created GIF
        if os.path.exists(gif_path):
            try:
                os.remove(gif_path)
            except OSError:
                pass
        return None

# Remove the compress_gif function and replace with a stub that always returns True
def compress_gif(gif_path):
    """Placeholder function - no compression is performed."""
    if not gif_path or not os.path.exists(gif_path):
        logging.error(f"GIF path is invalid or file not found: {gif_path}")
        return False
    
    # Log the original size for information only
    original_size = os.path.getsize(gif_path)
    logging.info(f"GIF size: {original_size / (1024*1024):.2f} MB (compression disabled)")
    
    return True  # Always return success since compression is disabled

def convert_to_gif_ffmpeg(video_path, gif_path, fps=15, width=480):
    """Converts video to GIF using ffmpeg for potentially better quality."""
    palette_path = os.path.splitext(gif_path)[0] + "_palette.png"
    
    # Add vf filter for scaling and fps
    filters = f"fps={fps},scale={width}:-1:flags=lanczos"

    # Pass 1: Generate palette
    ffmpeg_cmd_palette = [
        'ffmpeg',
        '-i', video_path,
        '-vf', f"{filters},palettegen",
        '-y', # Overwrite output file if it exists
        palette_path
    ]
    logging.info(f"Generating palette: {' '.join(ffmpeg_cmd_palette)}")
    try:
        subprocess.run(ffmpeg_cmd_palette, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"ffmpeg palette generation failed: {e}")
        logging.error(f"Stderr: {e.stderr.decode()}")
        if os.path.exists(palette_path): os.remove(palette_path)
        return None
    except FileNotFoundError:
        logging.error("ffmpeg command not found. Ensure ffmpeg is installed and in your PATH.")
        return None

    # Pass 2: Convert using palette
    ffmpeg_cmd_convert = [
        'ffmpeg',
        '-i', video_path,
        '-i', palette_path,
        '-lavfi', f"{filters} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", # Experiment with dither options
        '-y',
        gif_path
    ]
    logging.info(f"Converting using palette: {' '.join(ffmpeg_cmd_convert)}")
    try:
        subprocess.run(ffmpeg_cmd_convert, check=True, capture_output=True)
        if os.path.exists(palette_path):
            os.remove(palette_path) # Clean up palette
        if os.path.exists(gif_path):
             logging.info(f"FFmpeg GIF created successfully: {gif_path}")
             return gif_path
        else:
             logging.error("FFmpeg conversion finished but GIF file not found.")
             return None
    except subprocess.CalledProcessError as e:
        logging.error(f"ffmpeg conversion failed: {e}")
        logging.error(f"Stderr: {e.stderr.decode()}")
        if os.path.exists(palette_path): os.remove(palette_path)
        if os.path.exists(gif_path): os.remove(gif_path)
        return None
    except FileNotFoundError:
        logging.error("ffmpeg command not found. Ensure ffmpeg is installed and in your PATH.")
        if os.path.exists(palette_path): os.remove(palette_path)
        return None

# Keep the original convert_to_gif as fallback
def convert_to_gif(video_path, gif_path):
    """Legacy conversion method using MoviePy. Used as fallback if ffmpeg fails."""
    try:
        clip = VideoFileClip(video_path)
        clip.write_gif(gif_path, fps=15) # Increased FPS for smoother motion
        clip.close()
        logging.info(f"GIF created with MoviePy successfully: {gif_path}")
        
        if os.path.exists(gif_path):
            return gif_path
        else:
            logging.error(f"GIF file {gif_path} not found after creation.")
            return None

    except Exception as e:
        logging.error(f"Error converting video to GIF with MoviePy: {e}")
        # Clean up video file if conversion fails
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                logging.info(f"Cleaned up failed video file: {video_path}")
            except OSError as oe:
                logging.error(f"Error removing failed video file {video_path}: {oe}")
        # Clean up potentially partially created GIF
        if os.path.exists(gif_path):
            try:
                os.remove(gif_path)
            except OSError:
                pass
        return None # Return None on failure

# Add a new selenium-based extractor as final fallback
def extract_media_with_selenium(url, output_dir):
    """
    Use Selenium to extract media URLs from a Twitter post when all other methods fail.
    Returns (media_type, downloaded_paths) or (None, None) on failure.
    """
    if not SELENIUM_AVAILABLE:
        logging.error("Selenium not available. Cannot use browser-based extraction.")
        return None, None
    
    tweet_id = get_tweet_id(url)
    if not tweet_id:
        logging.error("Could not extract tweet ID from URL.")
        return None, None
    
    logging.info("Attempting direct browser-based media extraction with Selenium...")
    
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = None
    media_type = None
    downloaded_paths = []
    
    try:
        # Initialize browser
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        # Wait for page to load
        time.sleep(5)  # Simple wait for page content
        
        # Try to find video elements first
        video_elements = driver.find_elements(By.TAG_NAME, "video")
        if video_elements:
            logging.info(f"Found {len(video_elements)} video elements on page.")
            media_type = 'video'
            
            # Get the source of the first video
            video_url = None
            for video in video_elements:
                # Try to get direct src
                video_url = video.get_attribute("src")
                if not video_url:
                    # Try to get source from child source elements
                    source_elements = video.find_elements(By.TAG_NAME, "source")
                    if source_elements:
                        video_url = source_elements[0].get_attribute("src")
                
                if video_url:
                    logging.info(f"Found video URL: {video_url}")
                    break
            
            if video_url:
                # Download the video
                temp_video_path = os.path.join(output_dir, f"temp_media_{tweet_id}.mp4")
                
                try:
                    # Use requests to download the video
                    response = requests.get(video_url, stream=True, timeout=30, 
                                          headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                    with open(temp_video_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    if os.path.exists(temp_video_path) and os.path.getsize(temp_video_path) > 0:
                        logging.info(f"Video downloaded successfully via Selenium extraction: {temp_video_path}")
                        downloaded_paths.append(temp_video_path)
                    else:
                        logging.error("Video download via Selenium finished but file is empty or missing.")
                except Exception as download_err:
                    logging.error(f"Error downloading video with Selenium URL: {download_err}")
                    return None, None
        else:
            # No videos, try to find images
            image_elements = driver.find_elements(By.TAG_NAME, "img")
            if image_elements:
                media_type = 'image'
                logging.info(f"Found {len(image_elements)} image elements on page.")
                
                # Filter out small icons and get unique image URLs with good size
                image_urls = []
                processed_urls = set()
                
                for img in image_elements:
                    img_url = img.get_attribute("src")
                    
                    # Process only if URL exists and hasn't been seen
                    if img_url and img_url not in processed_urls:
                        processed_urls.add(img_url)
                        
                        # Skip small images (likely icons, avatars)
                        try:
                            width = int(img.get_attribute("width") or 0)
                            height = int(img.get_attribute("height") or 0)
                            if width < 100 or height < 100:
                                continue
                        except (ValueError, TypeError):
                            # If we can't determine size, include it anyway
                            pass
                        
                        # Check if URL is a data URL and skip if it is
                        if img_url.startswith("data:"):
                            continue
                            
                        # Check if it's likely the main tweet image
                        if "twimg" in img_url and ("media" in img_url or "pbs" in img_url):
                            image_urls.append(img_url)
                
                if not image_urls:
                    # If no good URLs found with filters, just take any non-data URLs as fallback
                    for img_url in processed_urls:
                        if not img_url.startswith("data:"):
                            image_urls.append(img_url)
                
                # Download images
                if image_urls:
                    logging.info(f"Found {len(image_urls)} potential image URLs to download.")
                    
                    for i, img_url in enumerate(image_urls):
                        try:
                            # Use requests to download
                            response = requests.get(img_url, stream=True, timeout=30,
                                                  headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                            response.raise_for_status()
                            
                            # Determine extension
                            content_type = response.headers.get('content-type', '')
                            if 'jpeg' in content_type or 'jpg' in content_type:
                                ext = '.jpg'
                            elif 'png' in content_type:
                                ext = '.png'
                            elif 'webp' in content_type:
                                ext = '.webp'
                            elif 'gif' in content_type:
                                ext = '.gif'
                            else:
                                ext = '.jpg'  # Default to jpg
                                
                            temp_image_path = os.path.join(output_dir, f"temp_media_{tweet_id}_{i+1}{ext}")
                            
                            with open(temp_image_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    
                            if os.path.exists(temp_image_path) and os.path.getsize(temp_image_path) > 0:
                                logging.info(f"Image {i+1} downloaded successfully via Selenium: {temp_image_path}")
                                downloaded_paths.append(temp_image_path)
                            else:
                                logging.warning(f"Image download via Selenium finished but file is empty: {temp_image_path}")
                                
                        except Exception as img_err:
                            logging.error(f"Error downloading image with Selenium: {img_err}")
                            # Continue with other images instead of failing
                            continue
            else:
                logging.error("No video or image elements found on the page.")
                return None, None
                
    except Exception as e:
        logging.exception(f"Error during Selenium-based extraction: {e}")
        return None, None
        
    finally:
        if driver:
            driver.quit()
    
    if not downloaded_paths:
        logging.error("Selenium extraction completed but no media files were downloaded.")
        return None, None
        
    return media_type, downloaded_paths

# Modified to handle different media types
def process_tweet_url(url):
    """Downloads media from Twitter URL and converts it to GIF."""
    if not re.match(r'https?://(www\.)?(twitter\.com|x\.com)/.+/status/\d+', url):
        logging.error("Invalid Twitter URL format.")
        return None

    output_dir = os.path.dirname(os.path.abspath(__file__))
    tweet_id = get_tweet_id(url)
    if not tweet_id:
        logging.error("Could not extract tweet ID for naming GIF.")
        return None

    gif_filename = f"tweet_{tweet_id}.gif"
    gif_path = os.path.join(output_dir, gif_filename)
    final_gif_path = None
    temp_media_paths = [] # Keep track of temp files

    try:
        with tempfile.TemporaryDirectory() as temp_download_dir:
            logging.info(f"Attempting to download media to {temp_download_dir}")
            media_type, temp_media_paths = download_media(url, temp_download_dir)

            if not media_type or not temp_media_paths:
                # New: Try selenium fallback if download_media fails
                logging.warning("Standard extraction methods failed. Trying browser-based extraction...")
                media_type, temp_media_paths = extract_media_with_selenium(url, temp_download_dir)
                
                if not media_type or not temp_media_paths:
                    logging.error("Failed to download media or determine type even with browser-based extraction.")
                    return None

            # --- Convert based on type ---
            if media_type == 'video':
                if len(temp_media_paths) == 1:
                    # Try ffmpeg-based conversion first
                    logging.info(f"Converting video to GIF using ffmpeg: {gif_path}")
                    final_gif_path = convert_to_gif_ffmpeg(temp_media_paths[0], gif_path, fps=15, width=640)
                    
                    # If ffmpeg fails, fall back to MoviePy
                    if not final_gif_path:
                        logging.warning("FFmpeg conversion failed, falling back to MoviePy...")
                        final_gif_path = convert_to_gif(temp_media_paths[0], gif_path)
                else:
                    logging.error("Expected one video path, but got multiple or none.")
                    return None
            elif media_type == 'image':
                 logging.info(f"Converting {len(temp_media_paths)} image(s) to GIF: {gif_path}")
                 # Try FFmpeg method first for images
                 final_gif_path = convert_images_to_gif_ffmpeg(temp_media_paths, gif_path)
                
                 # Fall back to PIL if FFmpeg fails
                 if not final_gif_path:
                     logging.warning("FFmpeg image-to-GIF conversion failed, falling back to PIL...")
                     final_gif_path = convert_images_to_gif(temp_media_paths, gif_path)
            else:
                 logging.error(f"Unsupported media type detected: {media_type}")
                 return None

            # Check if GIF was created successfully (no compression anymore)
            if final_gif_path and os.path.exists(final_gif_path):
                logging.info(f"Processing complete. Final GIF at: {final_gif_path}")
                return final_gif_path
            else:
                logging.error(f"Failed to create GIF from {media_type}.")
                return None

    except Exception as e:
        logging.exception(f"An unexpected error occurred during processing: {e}")
        return None
    # No finally block needed as TemporaryDirectory handles cleanup of temp_media_paths


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Download a video from a Twitter URL and convert it to a GIF.')
    parser.add_argument('url', type=str, help='The Twitter video URL')

    # Parse arguments
    args = parser.parse_args()

    # Call the processing function with the URL argument
    result_path = process_tweet_url(args.url)

    if result_path:
        print(f"Success! GIF created at: {result_path}") # Print success path for potential capture
        sys.exit(0) # Exit with success code
    else:
        print("Processing failed. Check logs for details.") # Print failure message
        sys.exit(1) # Exit with error code


if __name__ == "__main__":
    main()

def convert_images_to_gif_ffmpeg(image_paths, gif_path, fps=10):
    """
    Converts a sequence of images to an animated GIF using ffmpeg with palette optimization.
    This offers better quality than the PIL-based method.
    """
    if not image_paths:
        logging.error("No image paths provided for FFmpeg GIF conversion.")
        return None

    # First, ensure the image paths are sorted correctly
    image_paths = sorted(image_paths)
    
    # Create temporary directory for FFmpeg sequence
    with tempfile.TemporaryDirectory() as temp_seq_dir:
        # Create symbolic links or copies with sequential names for ffmpeg
        seq_paths = []
        for i, img_path in enumerate(image_paths):
            # Get original extension
            ext = os.path.splitext(img_path)[1]
            seq_name = f"seq_{i:04d}{ext}"
            seq_path = os.path.join(temp_seq_dir, seq_name)
            
            # Create copy of the image with sequential name
            try:
                shutil.copy2(img_path, seq_path)
                seq_paths.append(seq_path)
            except Exception as e:
                logging.error(f"Error copying image to sequence: {e}")
                return None

        if not seq_paths:
            logging.error("Failed to create image sequence for FFmpeg.")
            return None
            
        # Generate palette from the sequence
        palette_path = os.path.join(temp_seq_dir, "palette.png")
        pattern = os.path.join(temp_seq_dir, f"seq_%04d{ext}")
        
        # Determine frame rate based on number of images
        # Use slow frame rate for few images, faster for many
        if len(image_paths) <= 2:
            adjusted_fps = 1  # Very slow for 1-2 images
        elif len(image_paths) <= 5:
            adjusted_fps = 2  # Slow for 3-5 images
        else:
            adjusted_fps = fps  # Default for 6+ images
            
        # Step 1: Create palette
        palette_cmd = [
            'ffmpeg',
            '-f', 'image2',
            '-i', pattern,
            '-vf', f"fps={adjusted_fps},palettegen=stats_mode=single",
            '-y', palette_path
        ]
            
        logging.info(f"Generating palette for image sequence: {' '.join(palette_cmd)}")
        
        try:
            subprocess.run(palette_cmd, check=True, capture_output=True)
            
            if not os.path.exists(palette_path):
                logging.error("Failed to generate palette for image sequence.")
                return None
                
            # Step 2: Convert using palette
            convert_cmd = [
                'ffmpeg',
                '-f', 'image2',
                '-i', pattern,
                '-i', palette_path,
                '-filter_complex', f"fps={adjusted_fps}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                '-y', gif_path
            ]
            
            logging.info(f"Creating GIF from image sequence: {' '.join(convert_cmd)}")
            
            subprocess.run(convert_cmd, check=True, capture_output=True)
            
            if os.path.exists(gif_path):
                logging.info(f"FFmpeg image-to-GIF created successfully: {gif_path}")
                return gif_path
            else:
                logging.error("FFmpeg image-to-GIF conversion failed: output file not found.")
                return None
                
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg error during image-to-GIF conversion: {e}")
            if e.stderr:
                logging.error(f"FFmpeg stderr: {e.stderr.decode()}")
            if os.path.exists(gif_path):
                try:
                    os.remove(gif_path)
                except OSError:
                    pass
            return None
        except FileNotFoundError:
            logging.error("FFmpeg command not found. Ensure FFmpeg is installed and in your PATH.")
            return None
