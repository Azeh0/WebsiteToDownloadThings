import os
from datetime import datetime  # Add missing import
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging

# Import the functions from your existing scripts
from TwitterLinktoGIF import process_tweet_url
from YouTube_Downloader import download_youtube_video  # Import the new function

# Configure logging for the Flask app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
CORS(app)

# Define the directory where files are saved
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/process-twitter', methods=['POST'])
def handle_twitter_request():
    """Handles POST requests to process a Twitter URL."""
    # ADD THIS LINE:
    logging.info(f"--- Twitter POST request received ---")
    data = request.get_json()
    if not data or 'url' not in data:
        logging.error("Request missing 'url' in JSON body.")
        return jsonify({'status': 'Error', 'message': 'Missing URL in request'}), 400

    url = data['url']
    logging.info(f"Received request to process Twitter URL: {url}")

    try:
        # Call the processing function
        result_path = process_tweet_url(url)

        if result_path:
            logging.info(f"Successfully processed URL. GIF at: {result_path}")
            # Return only the filename for security/simplicity, construct download URL later
            filename = os.path.basename(result_path)
            # Create a URL the frontend can use to fetch the GIF
            download_url = f"/downloads/{filename}"
            return jsonify({'status': 'Success', 'path': result_path, 'downloadUrl': download_url})
        else:
            logging.error(f"Failed to process URL: {url}")
            return jsonify({'status': 'Error', 'message': 'Failed to download or convert video. Check backend logs.'}), 500
    except Exception as e:
        logging.exception(f"An unexpected error occurred while processing {url}: {e}")
        return jsonify({'status': 'Error', 'message': f'An internal server error occurred: {e}'}), 500

@app.route('/process-youtube', methods=['POST'])
def handle_youtube_request():
    """Handles POST requests to process a YouTube URL."""
    # ADD THIS LINE:
    logging.info(f"--- YouTube POST request received ---")
    logging.info(f"YouTube endpoint called with method: {request.method}")
    # Print all request headers to debug potential issues
    logging.info(f"Request headers: {dict(request.headers)}")
    
    try:
        data = request.get_json()
        logging.info(f"Request data received: {data}")
        
        if not data or 'url' not in data:
            logging.error("Request missing 'url' in JSON body.")
            return jsonify({'status': 'Error', 'message': 'Missing URL in request'}), 400

        url = data['url']
        quality = data.get('quality', 'best')
        format = data.get('format', 'mp4')
        
        logging.info(f"Processing YouTube URL: {url} with quality: {quality}, format: {format}")
        logging.info(f"Output directory: {OUTPUT_DIR}")
        logging.info(f"Directory exists: {os.path.exists(OUTPUT_DIR)}, Writable: {os.access(OUTPUT_DIR, os.W_OK)}")

        # Call the YouTube download function
        result_path = download_youtube_video(url, output_dir=OUTPUT_DIR, quality=quality, format=format)
        
        if result_path:
            logging.info(f"Download successful. File at: {result_path}")
            logging.info(f"File exists: {os.path.exists(result_path)}, Size: {os.path.getsize(result_path)} bytes")
            
            filename = os.path.basename(result_path)
            download_url = f"/downloads/{filename}"
            
            response_data = {
                'status': 'Success', 
                'path': result_path, 
                'downloadUrl': download_url,
                'filename': filename
            }
            logging.info(f"Sending response: {response_data}")
            return jsonify(response_data)
        else:
            logging.error(f"Failed to process YouTube URL: {url}")
            return jsonify({'status': 'Error', 'message': 'Failed to download video. Check backend logs.'}), 500
    except Exception as e:
        logging.exception(f"An unexpected error occurred while processing YouTube request: {e}")
        return jsonify({'status': 'Error', 'message': f'An internal server error occurred: {e}'}), 500

@app.route('/downloads/<filename>')
def download_file(filename):
    """Serves files from the output directory."""
    logging.info(f"Request to download file: {filename}")
    try:
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
    except FileNotFoundError:
        logging.error(f"File not found for download: {filename}")
        return jsonify({'status': 'Error', 'message': 'File not found.'}), 404
    except Exception as e:
        logging.exception(f"Error serving file {filename}: {e}")
        return jsonify({'status': 'Error', 'message': 'Could not serve file.'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Simple endpoint to verify the server is running and reachable."""
    logging.info("Health check endpoint called")
    return jsonify({
        'status': 'OK',
        'server': 'YouTubeDownloader API',
        'timestamp': str(datetime.now())
    })

if __name__ == '__main__':
    # Update logging before starting the server
    logging.info("Starting Flask server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
