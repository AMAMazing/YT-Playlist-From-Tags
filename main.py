import sys
import os
from collections import Counter

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
                             QLabel, QProgressBar, QTableWidget, QLineEdit,
                             QTextEdit, QRadioButton, QMessageBox,
                             QTableWidgetItem, QHeaderView, QGroupBox)
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtGui import QFont

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/youtube']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CLIENT_SECRETS_FILE = 'client_secrets.json'
TOKEN_FILE = 'token.json'

class YouTubeWorker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    tags_ready = pyqtSignal(object)
    playlist_created = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.credentials = None
        self.all_videos = []

    def run_analysis(self):
        try:
            self.progress.emit(0, "Authenticating...")
            if not self.authenticate():
                # Error is emitted from authenticate()
                return

            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)
            
            self.progress.emit(10, "Fetching channel information...")
            channels_response = youtube.channels().list(mine=True, part='contentDetails').execute()
            uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            video_ids = self._get_all_video_ids(youtube, uploads_playlist_id)

            all_tags = []
            self.all_videos.clear()
            self.progress.emit(40, "Fetching video details...")
            for i in range(0, len(video_ids), 50):
                videos_response = youtube.videos().list(id=','.join(video_ids[i:i+50]), part='snippet').execute()
                for item in videos_response['items']:
                    tags = item['snippet'].get('tags', [])
                    all_tags.extend(tags)
                    self.all_videos.append({'id': item['id'], 'tags': tags})
                
                progress_val = 40 + int(((i + 50) / len(video_ids)) * 50)
                self.progress.emit(progress_val, f"Analyzing video {min(i+50, len(video_ids))}/{len(video_ids)}...")

            tag_counts = Counter(all_tags)
            sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)
            
            self.progress.emit(100, "Analysis complete.")
            self.tags_ready.emit(sorted_tags)
            
        except Exception as e:
            self.error.emit(f"An error occurred during analysis: {e}")
        finally:
            self.finished.emit()

    def create_playlist(self, title, description, privacy, tag):
        try:
            if not self.credentials or not self.credentials.valid:
                self.progress.emit(0, "Re-authenticating...")
                if not self.authenticate():
                    return
            
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)

            self.progress.emit(10, f"Creating playlist '{title}'...")
            playlist_response = youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title, "description": description},
                    "status": {"privacyStatus": privacy}
                }
            ).execute()
            new_playlist_id = playlist_response['id']

            videos_to_add = [video['id'] for video in self.all_videos if tag in video.get('tags', [])]
            
            if not videos_to_add:
                self.playlist_created.emit(title, 0)
                return

            self.progress.emit(20, f"Adding {len(videos_to_add)} videos...")
            for i, video_id in enumerate(videos_to_add):
                youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": new_playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id}
                        }
                    }
                ).execute()
                progress_val = 20 + int(((i + 1) / len(videos_to_add)) * 80)
                self.progress.emit(progress_val, f"Added video {i+1}/{len(videos_to_add)}...")

            self.playlist_created.emit(title, len(videos_to_add))

        except Exception as e:
            self.error.emit(f"Playlist creation error: {e}")
        finally:
            self.finished.emit()

    def authenticate(self):
        creds = None
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    self.error.emit(f"Token refresh failed: {e}. Please connect again.")
                    return False
            else:
                if not os.path.exists(CLIENT_SECRETS_FILE):
                    self.error.emit("CLIENT_SECRETS_MISSING")
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        
        self.credentials = creds
        return self.credentials is not None

    def _get_all_video_ids(self, youtube_service, playlist_id):
        video_ids = []
        next_page_token = None
        self.progress.emit(20, "Fetching video list...")
        while True:
            res = youtube_service.playlistItems().list(
                playlistId=playlist_id, part='contentDetails', maxResults=50, pageToken=next_page_token
            ).execute()
            video_ids.extend([item['contentDetails']['videoId'] for item in res['items']])
            next_page_token = res.get('nextPageToken')
            if not next_page_token:
                break
        return video_ids

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Tag Analyzer & Playlist Creator")
        self.setGeometry(100, 100, 900, 700)
        self.youtube_worker = YouTubeWorker()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self.connect_button = QPushButton("Connect & Analyze Channel")
        self.connect_button.setFont(QFont("Arial", 12))
        self.connect_button.clicked.connect(self.start_analysis)
        main_layout.addWidget(self.connect_button)

        self.tag_table = QTableWidget()
        self.tag_table.setColumnCount(2)
        self.tag_table.setHorizontalHeaderLabels(["Tag Name", "Video Count"])
        self.tag_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tag_table.setSortingEnabled(True)
        self.tag_table.itemSelectionChanged.connect(self.on_tag_selected)
        main_layout.addWidget(self.tag_table)
        
        self._create_playlist_area(main_layout)

        status_layout = QVBoxLayout()
        self.status_label = QLabel("Ready.")
        self.progress_bar = QProgressBar()
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        main_layout.addLayout(status_layout)

    def _create_playlist_area(self, main_layout):
        self.playlist_group_box = QGroupBox("Create Playlist from Tag")
        self.playlist_group_box.setEnabled(False)
        playlist_layout = QVBoxLayout()

        self.selected_tag_label = QLabel("Selected Tag: None")
        self.playlist_name_input = QLineEdit()
        self.playlist_name_input.setPlaceholderText("New Playlist Name")
        
        self.playlist_desc_input = QTextEdit()
        self.playlist_desc_input.setPlaceholderText("Playlist Description (Optional)")
        self.playlist_desc_input.setFixedHeight(80)

        privacy_layout = QVBoxLayout()
        self.public_radio = QRadioButton("Public")
        self.public_radio.setChecked(True)
        self.private_radio = QRadioButton("Private")
        self.unlisted_radio = QRadioButton("Unlisted")
        privacy_layout.addWidget(self.public_radio)
        privacy_layout.addWidget(self.private_radio)
        privacy_layout.addWidget(self.unlisted_radio)

        self.create_playlist_button = QPushButton("Create Playlist")
        self.create_playlist_button.clicked.connect(self.confirm_and_create_playlist)

        playlist_layout.addWidget(self.selected_tag_label)
        playlist_layout.addWidget(self.playlist_name_input)
        playlist_layout.addWidget(self.playlist_desc_input)
        playlist_layout.addLayout(privacy_layout)
        playlist_layout.addWidget(self.create_playlist_button)
        
        self.playlist_group_box.setLayout(playlist_layout)
        main_layout.addWidget(self.playlist_group_box)

    def start_analysis(self):
        self._set_ui_enabled(False)
        self.progress_bar.setValue(0)
        
        self.worker_thread = QThread()
        self.youtube_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.youtube_worker.run_analysis)
        self._connect_worker_signals(self.youtube_worker)
        self.worker_thread.start()

    def confirm_and_create_playlist(self):
        if not self.tag_table.selectedItems():
            self.show_error("Please select a tag first.")
            return

        tag, count = self.tag_table.selectedItems()[0].text(), int(self.tag_table.item(self.tag_table.currentRow(), 1).text())
        name = self.playlist_name_input.text()
        
        reply = QMessageBox.question(self, 'Confirm Creation',
            f"Create playlist '{name}' with {count} videos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.start_playlist_creation(name, tag)

    def start_playlist_creation(self, name, tag):
        self._set_ui_enabled(False)
        self.progress_bar.setValue(0)

        description = self.playlist_desc_input.toPlainText()
        privacy = 'private' if self.private_radio.isChecked() else 'unlisted' if self.unlisted_radio.isChecked() else 'public'

        playlist_worker = YouTubeWorker()
        playlist_worker.all_videos = self.youtube_worker.all_videos
        self.worker_thread = QThread()
        playlist_worker.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(lambda: playlist_worker.create_playlist(name, description, privacy, tag))
        self._connect_worker_signals(playlist_worker)
        self.worker_thread.start()

    def update_status(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def show_error(self, message):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        
        if message == "CLIENT_SECRETS_MISSING":
            msg_box.setWindowTitle("Action Required: Setup Credentials")
            msg_box.setTextFormat(Qt.TextFormat.RichText)
            msg_box.setText(
                "The <strong>client_secrets.json</strong> file was not found.<br><br>"
                "To use this application, you need to get credentials from the Google Cloud Console. "
                "Please follow the instructions in the README file or visit the link below to create your credentials, "
                "download the JSON file, and place it in the application's directory.<br><br>"
                "<a href='https://console.cloud.google.com/apis/credentials'>Go to Google Cloud Credentials</a>"
            )
        else:
            msg_box.setWindowTitle("Error")
            msg_box.setText(message)
            
        msg_box.exec()
        self.status_label.setText("Error occurred.")
        self._set_ui_enabled(True)

    def populate_tags_table(self, tags):
        self.tag_table.setRowCount(len(tags))
        for row, (tag, count) in enumerate(tags):
            self.tag_table.setItem(row, 0, QTableWidgetItem(tag))
            self.tag_table.setItem(row, 1, QTableWidgetItem(str(count)))
        self.status_label.setText(f"Analysis complete. Found {len(tags)} unique tags.")
    
    def on_tag_selected(self):
        if not self.tag_table.selectedItems(): return

        selected_tag = self.tag_table.selectedItems()[0].text()
        self.selected_tag_label.setText(f"Selected Tag: {selected_tag}")
        self.playlist_name_input.setText(' '.join(word.capitalize() for word in selected_tag.split()))
        self.playlist_group_box.setEnabled(True)

    def on_playlist_created(self, title, count):
        QMessageBox.information(self, "Success", f"Successfully created playlist '{title}' with {count} videos!")
        self.status_label.setText("Playlist creation successful.")

    def _connect_worker_signals(self, worker):
        worker.finished.connect(self.worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(lambda: self._set_ui_enabled(True))
        worker.progress.connect(self.update_status)
        worker.error.connect(self.show_error)
        
        if hasattr(worker, 'tags_ready'):
            worker.tags_ready.connect(self.populate_tags_table)
        if hasattr(worker, 'playlist_created'):
            worker.playlist_created.connect(self.on_playlist_created)

    def _set_ui_enabled(self, enabled):
        self.connect_button.setEnabled(enabled)
        self.playlist_group_box.setEnabled(enabled and self.tag_table.rowCount() > 0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
