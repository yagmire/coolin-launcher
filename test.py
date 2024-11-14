import requests, threading, os
from time import sleep


# Define the URL and parameters
server_url = "http://localhost:2665/download"
params = {
    'game': '16',
    'version': 'latest'
}

# Path where the file will be saved
save_path = "16.zip"
# Create a function to download the file and update the progress bar
def download_file():
    global downloaded
    downloaded = False
    # Send GET request to the server with streaming enabled
    response = requests.get(server_url, params=params, stream=True)
    
    # Get the total size of the file from the headers
    downloaded_size = 0

    # Open the file where we will save the content
    with open(save_path, 'wb') as file:
        for data in response.iter_content(chunk_size=1024):
            if data:
                # Write the downloaded chunk to the file
                file.write(data)
                downloaded_size += len(data)
    downloaded = True

threading.Thread(target=download_file).start()
while downloaded == False:
    print("Downloading assets.. Please wait.")
    sleep(2)
print("Download complete.")