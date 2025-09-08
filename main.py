import sys
import os
import json
from collections import Counter

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
                             QLabel, QProgressBar, QTableWidget, QLineEdit,
                             QTextEdit, QMessageBox, QHBoxLayout,
                             QTableWidgetItem, QHeaderView, QFrame,
                             QSizePolicy, QAbstractButton, QButtonGroup,
                             QGraphicsDropShadowEffect, QSpacerItem)
from PyQt6.QtCore import (QThread, pyqtSignal, QObject, Qt, QPropertyAnimation,
                          QEasingCurve, pyqtProperty, QPointF)
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- Configuration Management ---
CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except json.JSONDecodeError: return {'theme': 'light'}
    return {'theme': 'light'}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)

# --- Google API Constants ---
SCOPES = ['https://www.googleapis.com/auth/youtube']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CLIENT_SECRETS_FILE = 'client_secrets.json'
TOKEN_FILE = 'token.json'

# --- Custom Themed Widgets ---

class AnimatedToggle(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True); self.setFixedSize(52, 32); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._handle_position = 0.0
        self.animation = QPropertyAnimation(self, b"handle_position", self)
        self.animation.setDuration(150); self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    @pyqtProperty(float)
    def handle_position(self): return self._handle_position
    @handle_position.setter
    def handle_position(self, pos): self._handle_position = pos; self.update()
    def paintEvent(self, e):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_dark = self.property("theme") == "dark"
        accent_color = QColor("#0A84FF") if is_dark else QColor("#007AFF")
        track_off_color = QColor("#444") if is_dark else QColor("#D1D1D6")
        track_color = accent_color if self.isChecked() else track_off_color
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QBrush(track_color)); painter.drawRoundedRect(self.rect(), 16, 16)
        handle_radius = self.height() / 2 - 2; handle_x = 2 + (self.width() - self.height()) * self._handle_position
        painter.setBrush(QBrush(QColor("white")))
        painter.drawEllipse(QPointF(handle_x + handle_radius, self.height() / 2), handle_radius, handle_radius)
    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.animation.setEndValue(1.0 if self.isChecked() else 0.0); self.animation.start()

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)

class ModernProgressBar(QProgressBar):
    def __init__(self): super().__init__(); self.setFixedHeight(4); self.setTextVisible(False)

class ModernButton(QPushButton):
    def __init__(self, text, style="primary"):
        super().__init__(text)
        self.setFont(QFont("SF Pro Display", 14, QFont.Weight.DemiBold)); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", f"ModernButton {style}")
        if style == "primary":
            self.setFixedHeight(48)

class ModernCard(QFrame):
    def __init__(self): super().__init__(); self.setProperty("class", "ModernCard")

class ModernLineEdit(QLineEdit):
    def __init__(self, placeholder=""): super().__init__(); self.setPlaceholderText(placeholder); self.setFont(QFont("SF Pro Display", 14)); self.setFixedHeight(48)

class ModernTextEdit(QTextEdit):
    def __init__(self, placeholder=""): super().__init__(); self.setPlaceholderText(placeholder); self.setFont(QFont("SF Pro Display", 14)); self.setMinimumHeight(96); self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

class ModernTable(QTableWidget):
    def __init__(self): super().__init__(); self.setFont(QFont("SF Pro Display", 13)); self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.setShowGrid(False); self.verticalHeader().setVisible(False); self.setAlternatingRowColors(False)

# --- YouTube API Worker ---
class YouTubeWorker(QObject):
    finished = pyqtSignal(); error = pyqtSignal(str); progress = pyqtSignal(int, str); tags_ready = pyqtSignal(object); playlist_created = pyqtSignal(str, int)
    def __init__(self): super().__init__(); self.credentials = None; self.all_videos = []
    def run_analysis(self):
        try:
            self.progress.emit(0, "Authenticating with YouTube...");
            if not self.authenticate(): return
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)
            self.progress.emit(10, "Fetching channel information...")
            channels_response = youtube.channels().list(mine=True, part='contentDetails').execute()
            uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            video_ids = self._get_all_video_ids(youtube, uploads_playlist_id)
            all_tags_raw, self.all_videos = [], []
            self.progress.emit(40, "Analyzing video tags...")
            for i in range(0, len(video_ids), 50):
                chunk_ids = ','.join(video_ids[i:i+50])
                videos_response = youtube.videos().list(id=chunk_ids, part='snippet').execute()
                for item in videos_response['items']:
                    tags = item['snippet'].get('tags', []); all_tags_raw.extend(tags)
                    # Store all tags as lowercase for case-insensitive matching later
                    self.all_videos.append({'id': item['id'], 'tags': [t.lower() for t in tags]})
                progress_val = 40 + int(((i + 50) / len(video_ids)) * 50); self.progress.emit(progress_val, f"Processed {min(i+50, len(video_ids))} of {len(video_ids)} videos")
            
            # Case-insensitive tag grouping logic
            tag_counts = Counter(tag.lower() for tag in all_tags_raw)
            # Create a map to remember the most frequent original casing for each lowercase tag
            original_casing_map = {tag.lower(): tag for tag in reversed(all_tags_raw)}
            
            processed_tags = []
            for tag_lower, count in tag_counts.items():
                original_case = original_casing_map.get(tag_lower, tag_lower)
                processed_tags.append((original_case, count))
            
            sorted_tags = sorted(processed_tags, key=lambda item: item[1], reverse=True)
            self.progress.emit(100, "Analysis complete"); self.tags_ready.emit(sorted_tags)
        except Exception as e: self.error.emit(f"Analysis failed: {e}")
        finally: self.finished.emit()
    def create_playlist(self, title, description, privacy, tag):
        try:
            if not self.credentials or not self.credentials.valid:
                self.progress.emit(0, "Re-authenticating...");
                if not self.authenticate(): return
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)
            self.progress.emit(10, "Creating playlist...")
            playlist_response = youtube.playlists().insert(part="snippet,status", body={"snippet": {"title": title, "description": description}, "status": {"privacyStatus": privacy}}).execute()
            new_playlist_id = playlist_response['id']; videos_to_add = [video['id'] for video in self.all_videos if tag.lower() in video.get('tags', [])]
            if not videos_to_add: self.playlist_created.emit(title, 0); return
            self.progress.emit(20, "Adding videos to playlist...")
            for i, video_id in enumerate(videos_to_add):
                youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": new_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
                progress_val = 20 + int(((i + 1) / len(videos_to_add)) * 80); self.progress.emit(progress_val, f"Added {i+1} of {len(videos_to_add)} videos")
            self.playlist_created.emit(title, len(videos_to_add))
        except Exception as e: self.error.emit(f"Failed to create playlist: {e}")
        finally: self.finished.emit()
    def authenticate(self):
        creds = None
        if os.path.exists(TOKEN_FILE): creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try: creds.refresh(Request())
                except Exception as e:
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    self.error.emit(f"Token refresh failed: {e}"); return False
            else:
                if not os.path.exists(CLIENT_SECRETS_FILE): self.error.emit("CLIENT_SECRETS_MISSING"); return False
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES); creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, 'w') as token: token.write(creds.to_json())
        self.credentials = creds
        return self.credentials is not None
    def _get_all_video_ids(self, youtube_service, playlist_id):
        video_ids, next_page_token = [], None
        self.progress.emit(20, "Fetching video list...")
        while True:
            res = youtube_service.playlistItems().list(playlistId=playlist_id, part='contentDetails', maxResults=50, pageToken=next_page_token).execute()
            video_ids.extend([item['contentDetails']['videoId'] for item in res['items']]); next_page_token = res.get('nextPageToken')
            if not next_page_token: break
        return video_ids


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Tag Analyzer"); self.setMinimumSize(1200, 850); self.resize(1280, 850)
        self.youtube_worker = YouTubeWorker(); self.config = load_config(); self.is_tall_layout = True
        self.init_ui()
        self.apply_theme(self.config.get('theme', 'light'))
        self.start_analysis()
    def init_ui(self):
        main_layout = QVBoxLayout(self); main_layout.setSpacing(24); main_layout.setContentsMargins(32, 24, 32, 24)
        # Header
        self.header_layout = QHBoxLayout()
        title_layout = QVBoxLayout(); title_layout.setSpacing(4)
        title = QLabel("YouTube Tag Analyzer"); title.setFont(QFont("SF Pro Display", 28, QFont.Weight.Bold)); title.setObjectName("TitleLabel")
        subtitle = QLabel("Analyze your channel's tags and create playlists automatically"); subtitle.setFont(QFont("SF Pro Display", 16)); subtitle.setObjectName("SubtitleLabel")
        title_layout.addWidget(title); title_layout.addWidget(subtitle)
        self.header_layout.addLayout(title_layout); self.header_layout.addStretch()
        
        self.theme_layout_widget = QWidget()
        theme_layout = QHBoxLayout(self.theme_layout_widget); theme_layout.setContentsMargins(0,0,0,0); theme_layout.setSpacing(8)
        self.sun_icon = QLabel("☀️"); self.sun_icon.setFont(QFont("Segoe UI Emoji", 14))
        self.theme_toggle = AnimatedToggle(); self.theme_toggle.toggled.connect(self._on_theme_toggled)
        self.moon_icon = QLabel("🌙"); self.moon_icon.setFont(QFont("Segoe UI Emoji", 14))
        theme_layout.addWidget(self.sun_icon); theme_layout.addWidget(self.theme_toggle); theme_layout.addWidget(self.moon_icon)
        
        self.action_button = ModernButton("Create Playlist", "primary"); self.action_button.clicked.connect(self.confirm_and_create_playlist); self.action_button.setMinimumWidth(180)
        main_layout.addLayout(self.header_layout)
        
        # Main content area
        content_layout = QHBoxLayout(); content_layout.setSpacing(24)
        tags_card = ModernCard(); tags_card_layout = QVBoxLayout(tags_card); tags_card_layout.setContentsMargins(0, 20, 0, 0); tags_card_layout.setSpacing(16)
        tags_header_layout = QHBoxLayout(); tags_header_layout.setContentsMargins(24,0,24,0)
        tags_header = QLabel("Tag Analysis"); tags_header.setFont(QFont("SF Pro Display", 20, QFont.Weight.Bold))
        tags_header_layout.addWidget(tags_header)
        self.tag_table = ModernTable(); self.tag_table.setColumnCount(2); self.tag_table.setHorizontalHeaderLabels(["TAG", "COUNT"]); self.tag_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch); self.tag_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed); self.tag_table.setColumnWidth(1, 120); self.tag_table.setSortingEnabled(True); self.tag_table.itemSelectionChanged.connect(self.on_tag_selected)
        tags_card_layout.addLayout(tags_header_layout); tags_card_layout.addWidget(self.tag_table)
        playlist_card_container = QWidget()
        right_layout = QVBoxLayout(playlist_card_container); right_layout.setContentsMargins(0,0,0,0)
        self.playlist_card = ModernCard(); self.playlist_card.setEnabled(False)
        self.playlist_card_layout = QVBoxLayout(self.playlist_card); self.playlist_card_layout.setContentsMargins(24, 24, 24, 24); self.playlist_card_layout.setSpacing(12)
        playlist_header = QLabel("Create Playlist"); playlist_header.setFont(QFont("SF Pro Display", 20, QFont.Weight.Bold))
        self.selected_tag_label = QLabel("Select a tag to continue"); self.selected_tag_label.setFont(QFont("SF Pro Display", 14)); self.selected_tag_label.setObjectName("SelectedTagLabel")
        name_label = QLabel("Playlist Name"); name_label.setFont(QFont("SF Pro Display", 13, QFont.Weight.DemiBold))
        self.playlist_name_input = ModernLineEdit()
        desc_label = QLabel("Description (Optional)"); desc_label.setFont(QFont("SF Pro Display", 13, QFont.Weight.DemiBold))
        self.playlist_desc_input = ModernTextEdit()
        privacy_label = QLabel("Privacy"); privacy_label.setFont(QFont("SF Pro Display", 13, QFont.Weight.DemiBold))
        self.privacy_selector = QButtonGroup(self)
        privacy_container = QFrame(); privacy_container.setObjectName("PrivacyContainer")
        privacy_layout = QVBoxLayout(privacy_container); privacy_layout.setContentsMargins(0,0,0,0); privacy_layout.setSpacing(0)
        options = ["Public", "Private", "Unlisted"]
        for i, option in enumerate(options):
            btn = QPushButton(option); btn.setCheckable(True); btn.setFont(QFont("SF Pro Display", 13, QFont.Weight.Medium)); btn.setMinimumHeight(44)
            if i == 0: btn.setChecked(True); btn.setProperty("position", "first")
            elif i == len(options) - 1: btn.setProperty("position", "last")
            else: btn.setProperty("position", "middle")
            privacy_layout.addWidget(btn); self.privacy_selector.addButton(btn)
        self.playlist_card_layout.addWidget(playlist_header); self.playlist_card_layout.addSpacing(8); self.playlist_card_layout.addWidget(self.selected_tag_label); self.playlist_card_layout.addSpacing(16); self.playlist_card_layout.addWidget(name_label); self.playlist_card_layout.addWidget(self.playlist_name_input); self.playlist_card_layout.addWidget(desc_label); self.playlist_card_layout.addWidget(self.playlist_desc_input); self.playlist_card_layout.addWidget(privacy_label); self.playlist_card_layout.addSpacing(4); self.playlist_card_layout.addWidget(privacy_container)        
        right_layout.addWidget(self.playlist_card)
        
        # --- Change for centering layout ---
        # Changed stretch factors from (6, 4) to (1, 1) for equal column widths
        content_layout.addWidget(tags_card, 1)
        content_layout.addWidget(playlist_card_container, 1)
        
        main_layout.addLayout(content_layout)
        # Status bar
        status_card = ModernCard(); status_layout = QHBoxLayout(status_card); status_layout.setContentsMargins(20, 16, 20, 16); status_layout.setSpacing(16)
        self.status_label = QLabel("Connecting to YouTube..."); self.status_label.setFont(QFont("SF Pro Display", 14)); self.status_label.setObjectName("StatusLabel")
        self.progress_bar = ModernProgressBar()
        status_layout.addWidget(self.status_label, 1); status_layout.addWidget(self.progress_bar, 1)
        main_layout.addWidget(status_card)
        # Initialize layout state
        self.update_layouts()
    def update_layouts(self):
        is_currently_tall = self.height() > 950 # Threshold for switching layouts
        if is_currently_tall == self.is_tall_layout and self.theme_layout_widget.parent() is not None: return
        self.is_tall_layout = is_currently_tall

        self.theme_layout_widget.setParent(None)
        self.action_button.setParent(None)
        
        last_item = self.playlist_card_layout.itemAt(self.playlist_card_layout.count() - 1)
        if isinstance(last_item, QHBoxLayout):
            while last_item.count():
                item = last_item.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self.playlist_card_layout.removeItem(last_item)
        # --- The line removing the spacer has also been deleted from here ---
        
        if self.is_tall_layout:
            # --- TALL VIEW ---
            self.header_layout.addWidget(self.theme_layout_widget)
            
            self.action_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.action_button.setFixedHeight(80) # Using your preferred height

            # --- The spacer is no longer added here. We just add the button directly. ---
            self.playlist_card_layout.addWidget(self.action_button)

        else:
            # --- COMPACT VIEW ---
            self.action_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self.action_button.setFixedHeight(48)
            
            self.header_layout.addWidget(self.theme_layout_widget)
            self.header_layout.addSpacing(20)
            self.header_layout.addWidget(self.action_button)

        self.apply_theme(self.config.get('theme', 'light'))
    def resizeEvent(self, event):
        super().resizeEvent(event); self.update_layouts()
    def _apply_shadow(self, widget, blur, x, y, color):
        shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(blur); shadow.setOffset(x, y); shadow.setColor(color); widget.setGraphicsEffect(shadow)
    def _on_theme_toggled(self, is_dark):
        theme = 'dark' if is_dark else 'light'; self.config['theme'] = theme; save_config(self.config); self.apply_theme(theme)
    def apply_theme(self, theme_name):
        is_dark = theme_name == 'dark'
        p = {
            "bg": "#1C1C1E" if is_dark else "#F2F2F7", "card_bg": "#2C2C2E" if is_dark else "#FFFFFF", "text_primary": "#1D1D1F" if not is_dark else "#FFFFFFE0",
            "text_secondary": "#6E6E73" if not is_dark else "#8D8D92", "accent": "#007AFF" if not is_dark else "#0A84FF", "accent_hover": "#0056CC" if not is_dark else "#3F9BFF",
            "input_bg": "#F2F2F7" if not is_dark else "#3A3A3C", "input_border": "#E5E5EA" if not is_dark else "#48484A", "shadow": QColor(0,0,0, 25) if not is_dark else QColor(0,0,0, 80),
            "disabled_bg": "#E5E5E7" if not is_dark else "#3A3A3C", "disabled_text": "#8E8E93" if not is_dark else "#6C6C70",
            "selection_bg": "#E8F5E9" if not is_dark else "#313D33",
            # --- FIX: Set checked privacy text to white for both themes for better contrast ---
            "privacy_checked_text": "white",
        }
        self.theme_toggle.setProperty("theme", theme_name); self.theme_toggle.setChecked(is_dark)
        self.setStyleSheet(f"""
            QWidget {{ background-color: {p['bg']}; outline: 0; }}
            ModernCard {{ background-color: {p['card_bg']}; border-radius: 16px; }}

            #TitleLabel {{ color: {p['text_primary']}; }} 
            #SubtitleLabel, #StatusLabel {{ color: {p['text_secondary']}; }}
            QLabel {{ color: {p['text_primary']}; background-color: transparent; }}

            ModernButton[class~="primary"] {{ background-color: {p['accent']}; color: white; border: none; border-radius: 12px; padding: 0 16px; }} 
            ModernButton[class~="primary"]:hover {{ background-color: {p['accent_hover']}; }}
            ModernButton[class~="primary"]:disabled {{ background-color: {p['disabled_bg']}; color: {p['disabled_text']}; }}
            ModernProgressBar {{ background-color: {p['input_bg']}; border: none; border-radius: 2px; }} ModernProgressBar::chunk {{ background-color: {p['accent']}; border-radius: 2px; }}
            ModernLineEdit, ModernTextEdit {{ background-color: {p['input_bg']}; border: 1px solid {p['input_border']}; border-radius: 12px; padding: 0 16px; color: {p['text_primary']}; }} ModernTextEdit {{ padding: 12px 16px; }} ModernLineEdit:focus, ModernTextEdit:focus {{ border-color: {p['accent']}; background-color: {p['card_bg']}; }}
            ModernTable {{ background-color: {p['card_bg']}; border: none; color: {p['text_primary']}; }} ModernTable::item {{ padding: 14px 24px; border-bottom: 1px solid {p['input_bg']}; }} ModernTable::item:selected {{ background-color: {p['selection_bg']}; color: {p['accent']}; }}
            QHeaderView::section {{ background-color: {p['card_bg']}; color: {p['text_secondary']}; padding: 12px 24px; border: none; border-bottom: 2px solid {p['input_bg']}; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
            #SelectedTagLabel {{ background-color: {p['input_bg']}; color: {p['text_secondary']}; padding: 12px 16px; border-radius: 12px; }}
            #PrivacyContainer {{ border: 1px solid {p['input_border']}; border-radius: 12px; }}
            #PrivacyContainer QPushButton {{ background-color: transparent; border: none; color: {p['text_secondary']}; }} 
            #PrivacyContainer QPushButton:checked {{ background-color: {p['accent']}; color: {p['privacy_checked_text']}; font-weight: bold; }}
            #PrivacyContainer QPushButton[position="first"] {{ border-top-left-radius: 11px; border-top-right-radius: 11px; }} #PrivacyContainer QPushButton[position="last"] {{ border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }} #PrivacyContainer QPushButton[position="middle"] {{ border-top: 1px solid {p['input_border']}; border-bottom: 1px solid {p['input_border']}; }}
            QScrollBar:vertical {{ background: transparent; width: 14px; margin: 0; }} QScrollBar::handle:vertical {{ background-color: {p['input_bg']}; border-radius: 6px; min-height: 25px; }} QScrollBar::handle:vertical:hover {{ background-color: {p['input_border']}; }} QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::up-arrow, QScrollBar::down-arrow {{ height: 0; width: 0; }}
        """)
        for card in self.findChildren(ModernCard):
            self._apply_shadow(card, 35, 0, 5, p['shadow'])
        if self.tag_table.selectedItems(): self.on_tag_selected()
    def start_analysis(self): self._set_ui_enabled(False); self.progress_bar.setValue(0); self.worker_thread = QThread(); self.youtube_worker.moveToThread(self.worker_thread); self.worker_thread.started.connect(self.youtube_worker.run_analysis); self._connect_worker_signals(self.youtube_worker); self.worker_thread.start()
    def confirm_and_create_playlist(self):
        if not self.tag_table.selectedItems(): self.show_message("Please select a tag first.", "warning"); return
        tag = self.tag_table.selectedItems()[0].text(); count_text = self.tag_table.item(self.tag_table.currentRow(), 1).text(); name = self.playlist_name_input.text().strip()
        if not name: self.show_message("Please enter a playlist name.", "warning"); return
        if QMessageBox.question(self, 'Confirm Creation', f"Create playlist '{name}' with {count_text} videos tagged '{tag}'?") == QMessageBox.StandardButton.Yes: self.start_playlist_creation(name, tag)
    def start_playlist_creation(self, name, tag):
        self._set_ui_enabled(False); self.progress_bar.setValue(0); description = self.playlist_desc_input.toPlainText(); privacy = self.privacy_selector.checkedButton().text().lower()
        playlist_worker = YouTubeWorker(); playlist_worker.all_videos = self.youtube_worker.all_videos; self.worker_thread = QThread(); playlist_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(lambda: playlist_worker.create_playlist(name, description, privacy, tag)); self._connect_worker_signals(playlist_worker); self.worker_thread.start()
    def update_status(self, value, message): self.progress_bar.setValue(value); self.status_label.setText(message)
    def show_message(self, message, type="info"):
        msg_box = QMessageBox(self); msg_box.setStyleSheet(self.styleSheet())
        if type == "error": msg_box.setIcon(QMessageBox.Icon.Critical); msg_box.setWindowTitle("Error")
        elif type == "warning": msg_box.setIcon(QMessageBox.Icon.Warning); msg_box.setWindowTitle("Warning")
        else: msg_box.setIcon(QMessageBox.Icon.Information); msg_box.setWindowTitle("Information")
        msg_box.setText(message); msg_box.exec()
    def show_error(self, message):
        if message == "CLIENT_SECRETS_MISSING": self.show_message("<p><b>Missing client_secrets.json file.</b></p><p>Please download your OAuth 2.0 credentials from the Google Cloud Console and place the file in the application's folder.</p>", "error")
        else: self.show_message(message, "error")
        self.status_label.setText("Error occurred"); self._set_ui_enabled(True)
    def populate_tags_table(self, tags):
        self.tag_table.setSortingEnabled(False); self.tag_table.setRowCount(0); self.tag_table.setRowCount(len(tags))
        for row, (tag, count) in enumerate(tags):
            tag_item = QTableWidgetItem(tag); count_item = NumericTableWidgetItem()
            count_item.setData(Qt.ItemDataRole.DisplayRole, str(count)); count_item.setData(Qt.ItemDataRole.UserRole, int(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tag_table.setItem(row, 0, tag_item); self.tag_table.setItem(row, 1, count_item)
        self.tag_table.setSortingEnabled(True); self.tag_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.status_label.setText(f"Found {len(tags)} unique tags. Select one to create a playlist.")
    def on_tag_selected(self):
        if not self.tag_table.selectedItems(): return
        selected_tag = self.tag_table.selectedItems()[0].text(); count = self.tag_table.item(self.tag_table.currentRow(), 1).text()
        self.selected_tag_label.setText(f"{selected_tag} • {count} videos")
        is_dark = self.config.get('theme') == 'dark'
        accent_color = "#0A84FF" if is_dark else "#007AFF"
        selection_bg = "#E8F5E9" if not is_dark else "#313D33" # Using light green selection color
        self.selected_tag_label.setStyleSheet(f"#SelectedTagLabel {{ background-color: {selection_bg}; color: {accent_color}; padding: 12px 16px; border-radius: 12px; font-weight: 500; }}")
        self.playlist_name_input.setText(' '.join(word.capitalize() for word in selected_tag.split())); self.playlist_card.setEnabled(True)
        self._set_ui_enabled(True)
    def on_playlist_created(self, title, count): self.show_message(f"Successfully created playlist '{title}' with {count} videos!", "info"); self.status_label.setText("Playlist created successfully")
    def _connect_worker_signals(self, worker):
        worker.finished.connect(self.worker_thread.quit); worker.finished.connect(worker.deleteLater); self.worker_thread.finished.connect(self.worker_thread.deleteLater); self.worker_thread.finished.connect(lambda: self._set_ui_enabled(True))
        worker.progress.connect(self.update_status); worker.error.connect(self.show_error)
        if hasattr(worker, 'tags_ready'): worker.tags_ready.connect(self.populate_tags_table)
        if hasattr(worker, 'playlist_created'): worker.playlist_created.connect(self.on_playlist_created)
    def _set_ui_enabled(self, enabled):
        is_tag_selected = bool(self.tag_table.selectedItems())
        self.action_button.setEnabled(enabled and is_tag_selected)
        self.playlist_card.setEnabled(enabled and is_tag_selected)
if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("SF Pro Display", 13)
    if sys.platform == "win32": font = QFont("Segoe UI", 9)
    elif sys.platform != "darwin": font = QFont("Ubuntu", 10)
    app.setFont(font)
    window = MainWindow(); window.show()
    sys.exit(app.exec())