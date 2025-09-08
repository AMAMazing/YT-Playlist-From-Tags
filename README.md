# YouTube Tag Analyzer & Playlist Creator

This is a desktop application for YouTube creators that analyzes the tags of all uploaded videos and allows for the creation of new playlists based on the most frequently used tags.

## Features

- Securely connects to your YouTube account using OAuth 2.0.
- Fetches and analyzes all your videos to find the most used tags.
- Displays a sorted list of tags by frequency.
- Allows you to create new playlists (Public, Private, or Unlisted) from a selected tag.
- Adds all videos with the selected tag to the new playlist.

## Setup Instructions

### 1. Set up Google Cloud Project & Credentials

Before you can use this application, you need to obtain credentials from the Google Cloud Platform.

1.  **Go to the Google Cloud Console:** [https://console.cloud.google.com/](https://console.cloud.google.com/)
2.  **Create a new project:**
    *   Click the project drop-down and select "New Project".
    *   Give it a name (e.g., "YT Playlist App") and click "Create".
3.  **Enable the YouTube Data API v3:**
    *   In the navigation menu, go to "APIs & Services" > "Library".
    *   Search for "YouTube Data API v3" and click on it.
    *   Click the "Enable" button.
4.  **Configure the OAuth Consent Screen:**
    *   Go to "APIs & Services" > "OAuth consent screen".
    *   Choose "External" for the User Type and click "Create".
    *   Fill in the required app information (App name, User support email, Developer contact information).
    *   On the "Scopes" page, click "Add or Remove Scopes". Find the `.../auth/youtube` scope (`https://www.googleapis.com/auth/youtube`), select it, and click "Update".
    *   On the "Test users" page, add your Google account's email address. This allows you to test the app before it's published.
5.  **Create Credentials:**
    *   Go to "APIs & Services" > "Credentials".
    *   Click "+ CREATE CREDENTIALS" and select "OAuth client ID".
    *   For "Application type", choose "Desktop app".
    *   Give it a name and click "Create".
    *   A dialog will appear with your client ID and client secret. Click "DOWNLOAD JSON" to save the file.
6.  **Rename and Place the File:**
    *   Rename the downloaded JSON file to `client_secrets.json`.
    *   Place this `client_secrets.json` file in the same directory as the application's main script.

### 2. Install Dependencies

Make sure you have Python 3.8+ installed. You can install the necessary packages using pip and the `requirements.txt` file.

Open your terminal or command prompt and run:
```
pip install -r requirements.txt
```

### 3. Run the Application

Once the dependencies are installed and `client_secrets.json` is in place, you can run the application:

```
python main.py
```

The first time you run it, you will be prompted to authorize the application through your web browser. Follow the steps to grant access to your YouTube account. A `token.json` file will be created to store your credentials for future launches.

