document.addEventListener('DOMContentLoaded', () => {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    // --- Tab Switching Logic ---
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTabId = button.dataset.tab;
            const targetTabContent = document.getElementById(targetTabId);

            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            button.classList.add('active');
            if (targetTabContent) {
                targetTabContent.classList.add('active');
            }
        });
    });

    // --- Get Elements ---
    const youtubeInput = document.getElementById('youtube-link-input');
    const youtubeButton = document.getElementById('youtube-confirm-button');
    const youtubeLog = document.getElementById('youtube-log');

    const twitterInput = document.getElementById('twitter-link-input');
    const twitterButton = document.getElementById('twitter-confirm-button');
    const twitterLog = document.getElementById('twitter-log');

    const spotifyInput = document.getElementById('spotify-link-input');
    const spotifyButton = document.getElementById('spotify-confirm-button');
    const spotifyLog = document.getElementById('spotify-log');

    // --- Helper Function to Add Log Messages ---
    function addLogMessage(logArea, message) {
        const timestamp = new Date().toLocaleTimeString();
        logArea.value += `[${timestamp}] ${message}\n`;
        logArea.scrollTop = logArea.scrollHeight; // Scroll to bottom
    }

    // Add a server health check when the page loads
    checkServerAvailability();
    
    function checkServerAvailability() {
        const healthUrl = 'http://127.0.0.1:5000/health';
        console.log(`Attempting health check at: ${healthUrl}`); // Log the attempt
        fetch(healthUrl)
            .then(response => {
                console.log(`Health check response status: ${response.status}`); // Log status
                if (!response.ok) {
                    // Try to get more info from the response if possible
                    return response.text().then(text => {
                         throw new Error(`Server responded with status ${response.status}: ${text || 'No additional error info'}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                console.log('Server is available:', data);
                // Optional: Add a visual indicator that the server is online
                // e.g., document.getElementById('server-status').textContent = 'Online';
            })
            .catch(error => {
                // Log the specific error object
                console.error('Server health check failed:', error);
                // Provide a more informative alert
                alert(`Warning: Could not connect to the backend server at ${healthUrl}. Please ensure it is running and accessible. Error: ${error.message}`);
                // Optional: Add a visual indicator that the server is offline
                // e.g., document.getElementById('server-status').textContent = 'Offline';
            });
    }

    // --- Event Listeners for Confirm Buttons ---

    if (youtubeButton) {
        youtubeButton.addEventListener('click', () => {
            // ADD THIS LOG:
            console.log("YouTube Confirm button clicked. Preparing request for /process-youtube");
            const url = youtubeInput.value.trim();
            if (!url) {
                addLogMessage(youtubeLog, "Error: Please enter a YouTube URL.");
                return;
            }
            addLogMessage(youtubeLog, `Processing YouTube URL: ${url}`);
            addLogMessage(youtubeLog, "Sending request to backend...");
            
            // Add debugging for network requests
            console.log('Sending request to:', 'http://127.0.0.1:5000/process-youtube');
            console.log('Request body:', JSON.stringify({ 
                url: url,
                quality: 'best',
                format: 'mp4'
            }));
            
            // Make actual backend call to the Flask server
            fetch('http://127.0.0.1:5000/process-youtube', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: url,
                    quality: 'best',  // You could add UI for quality selection
                    format: 'mp4'     // You could add UI for format selection
                })
            })
            .then(response => {
                console.log('Response status:', response.status);
                if (!response.ok) {
                    return response.json().then(errData => {
                        throw new Error(errData.message || `HTTP error! status: ${response.status}`);
                    }).catch(() => {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                console.log('Response data:', data);
                addLogMessage(youtubeLog, `Backend: ${data.status}`);
                if (data.status === 'Success' && data.path) {
                    addLogMessage(youtubeLog, `Server path: ${data.path}`);
                    if (data.downloadUrl) {
                        const fullDownloadUrl = `http://127.0.0.1:5000${data.downloadUrl}`;
                        addLogMessage(youtubeLog, `Success! Starting download from ${fullDownloadUrl}`);
                        window.location.href = fullDownloadUrl; // Trigger download automatically
                    } else {
                        addLogMessage(youtubeLog, `Error: Backend succeeded but did not provide a download URL.`);
                    }
                } else if (data.message) {
                    addLogMessage(youtubeLog, `Error: ${data.message}`);
                }
            })
            .catch(error => {
                console.error("Fetch error:", error);
                addLogMessage(youtubeLog, `Error sending request: ${error.message}`);
                addLogMessage(youtubeLog, "Is the Flask server running? Check console for details.");
            });

            youtubeInput.value = ''; // Clear input after processing
        });
    }

    if (twitterButton) {
        twitterButton.addEventListener('click', () => {
            // ADD THIS LOG:
            console.log("Twitter Confirm button clicked. Preparing request for /process-twitter");
            const url = twitterInput.value.trim();
            if (!url) {
                addLogMessage(twitterLog, "Error: Please enter a Twitter URL.");
                return;
            }
            addLogMessage(twitterLog, `Processing Twitter URL: ${url}`);
            addLogMessage(twitterLog, "Sending request to backend..."); // Update log message

            // --- Backend Call ---
            // Make sure Flask server (app.py) is running on http://127.0.0.1:5000
            fetch('http://127.0.0.1:5000/process-twitter', { // Use the Flask server address
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            })
            .then(response => {
                if (!response.ok) {
                    // Try to get error message from backend response body
                    return response.json().then(errData => {
                        throw new Error(errData.message || `HTTP error! status: ${response.status}`);
                    }).catch(() => {
                        // Fallback if response body is not JSON or empty
                        throw new Error(`HTTP error! status: ${response.status}`);
                    });
                }
                return response.json(); // Parse JSON body on success
            })
            .then(data => {
                addLogMessage(twitterLog, `Backend: ${data.status}`);
                if (data.status === 'Success' && data.path) {
                    addLogMessage(twitterLog, `Server path: ${data.path}`);
                    if (data.downloadUrl) {
                        // --- Auto-download Trigger ---
                        const fullDownloadUrl = `http://127.0.0.1:5000${data.downloadUrl}`;
                        addLogMessage(twitterLog, `Success! Starting download from ${fullDownloadUrl}`);
                        window.location.href = fullDownloadUrl; // Trigger download automatically
                        // --- Remove link creation code ---
                        /*
                        const downloadLink = document.createElement('a');
                        downloadLink.href = `http://127.0.0.1:5000${data.downloadUrl}`;
                        downloadLink.textContent = `Download GIF: ${data.downloadUrl.split('/').pop()}`;
                        downloadLink.style.display = 'block';
                        downloadLink.style.marginTop = '10px';
                        downloadLink.style.color = 'var(--button-active-underline)';
                        twitterLog.parentNode.insertBefore(downloadLink, twitterLog.nextSibling);
                        addLogMessage(twitterLog, `Download link created.`);
                        */
                    } else {
                        addLogMessage(twitterLog, `Error: Backend succeeded but did not provide a download URL.`);
                    }
                } else if (data.message) {
                     addLogMessage(twitterLog, `Error: ${data.message}`);
                }
            })
            .catch(error => {
                console.error("Fetch error:", error); // Log detailed error to console
                addLogMessage(twitterLog, `Error sending request: ${error.message}`);
            });
            // --- End Backend Call ---
            twitterInput.value = ''; // Clear input
        });
    }

    if (spotifyButton) {
        spotifyButton.addEventListener('click', () => {
            const url = spotifyInput.value.trim();
            if (!url) {
                addLogMessage(spotifyLog, "Error: Please enter a Spotify URL.");
                return;
            }
            addLogMessage(spotifyLog, `Processing Spotify URL: ${url}`);
            addLogMessage(spotifyLog, "Note: Actual download requires a backend server.");
            // --- Backend Call Placeholder ---
            // Similar fetch() call to a '/process-spotify' endpoint would go here.
            // --- End Backend Call Placeholder ---
            spotifyInput.value = ''; // Clear input
        });
    }
});
