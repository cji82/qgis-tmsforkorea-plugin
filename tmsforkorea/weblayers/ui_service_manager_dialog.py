#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
/***************************************************************************
Service Manager Dialog
A QGIS plugin

                             -------------------
begin                : 2024-01-01
copyright            : (C) 2024 by Your Name
email                : your.email@example.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                                 QWidget, QPushButton,
                                 QLabel, QLineEdit, QTextEdit, QMessageBox,
                                 QGroupBox, QFormLayout, QSpinBox, QComboBox, QCheckBox,
                                 QProgressBar, QApplication, QFrame, QStackedWidget,
                                 QSizePolicy, QScrollArea)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.core import QgsMessageLog
import os
import re

# URL 업데이터 import
from .url_updater import MapServiceURLUpdater


def _msgbox_button(name):
    if hasattr(QMessageBox, name):
        return getattr(QMessageBox, name)
    if hasattr(QMessageBox, "StandardButton"):
        enum_cls = QMessageBox.StandardButton
        if hasattr(enum_cls, name):
            return getattr(enum_cls, name)
    raise AttributeError("QMessageBox button not found: {}".format(name))


def _qt_item_data_user_role():
    """PyQt5: Qt.UserRole / PyQt6: Qt.ItemDataRole.UserRole"""
    if hasattr(Qt, "UserRole"):
        return Qt.UserRole
    return Qt.ItemDataRole.UserRole


def _qt_text_format_rich():
    """PyQt5: Qt.RichText / PyQt6: Qt.TextFormat.RichText"""
    if hasattr(Qt, "RichText"):
        return Qt.RichText
    return Qt.TextFormat.RichText


def _size_policy_preferred_maximum():
    """그룹박스가 세로로 불필요하게 늘어나지 않도록"""
    if hasattr(QSizePolicy, "Policy"):
        return QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    return QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)


def _size_policy_expanding_fixed():
    """QTextEdit이 세로로 레이아웃 공간을 잡아먹지 않도록"""
    if hasattr(QSizePolicy, "Policy"):
        return QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


def _tile_version_from_urls(urls):
    """타일 URL에 포함된 버전(카카오 mts …/v…/latest/, 네이버 nrb …/styles/…/숫자/)."""
    if not urls:
        return None
    pat_kakao = re.compile(r"/(v\d+_[a-z0-9]+)/latest/", re.I)
    pat_naver = re.compile(r"/nrb/styles/(?:basic|satellite|terrain)/(\d+)(?:/|\?|$)", re.I)
    for u in urls:
        if not u or not isinstance(u, str):
            continue
        m = pat_kakao.search(u)
        if m:
            return m.group(1)
        m = pat_naver.search(u)
        if m:
            return m.group(1)
    return None


class URLUpdateWorker(QThread):
    """백그라운드에서 URL 업데이트를 수행하는 워커 스레드"""
    
    update_progress = pyqtSignal(str)
    update_finished = pyqtSignal(dict)
    update_error = pyqtSignal(str)
    
    def __init__(self, updater, proxy_cfg=None, include_services=None, kakao_api_key=""):
        super().__init__()
        self.updater = updater
        self.proxy_cfg = proxy_cfg or {}
        self.include_services = include_services or {
            "kakao": True,
            "naver": True,
            "vworld": True,
        }
        self.kakao_api_key = (kakao_api_key or "").strip()
    
    def run(self):
        try:
            self.updater.configure_proxies(self.proxy_cfg)
            self.updater.set_kakao_api_key(self.kakao_api_key)
            self.update_progress.emit("최신 URL을 가져오는 중...")
            results = {}
            if self.include_services.get("kakao"):
                results["kakao"] = self.updater.get_kakao_latest_urls()
            if self.include_services.get("naver"):
                results["naver"] = self.updater.get_naver_latest_urls()
            if self.include_services.get("vworld"):
                results["vworld"] = self.updater.get_vworld_latest_urls()
            self.update_finished.emit(results)
        except Exception as e:
            self.update_error.emit(str(e))

class ServiceManagerDialog(QDialog):
    """지도 서비스 설정 관리 다이얼로그"""
    
    configUpdated = pyqtSignal()
    
    def __init__(self, service_manager, parent=None, iface=None):
        super().__init__(parent)
        self.service_manager = service_manager
        self.iface = iface
        self.url_updater = MapServiceURLUpdater()
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        self.setWindowTitle("지도 서비스 설정 관리")
        self.setSizeGripEnabled(False)
        try:
            self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        except AttributeError:
            pass
        self.setMinimumSize(800, 520)
        self.setMaximumSize(800, 520)
        
        layout = QVBoxLayout()
        
        # 탭 위젯 생성
        self.tab_widget = QTabWidget()
        
        # 기존 설정 탭
        self.create_settings_tab()
        
        # 최신 URL 가져오기 탭
        self.create_url_update_tab()
        
        layout.addWidget(self.tab_widget)
        
        # 버튼
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("저장")
        self.save_button.clicked.connect(self.save_config)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def create_settings_tab(self):
        """기존 설정 탭 생성"""
        settings_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # 서비스 선택
        service_layout = QHBoxLayout()
        service_layout.addWidget(QLabel("서비스:"))
        self.service_combo = QComboBox()
        self.service_combo.currentTextChanged.connect(self.on_service_changed)
        service_layout.addWidget(self.service_combo)
        
        # 레이어 선택
        service_layout.addWidget(QLabel("레이어:"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentTextChanged.connect(self.on_layer_changed)
        self.layer_combo.currentIndexChanged.connect(self._on_layer_index_changed)
        service_layout.addWidget(self.layer_combo)
        
        # 서비스 추가/삭제 버튼
        self.add_service_btn = QPushButton("서비스 추가")
        self.add_service_btn.clicked.connect(self.add_service)
        self.remove_service_btn = QPushButton("서비스 삭제")
        self.remove_service_btn.clicked.connect(self.remove_service)
        
        service_layout.addWidget(self.add_service_btn)
        service_layout.addWidget(self.remove_service_btn)
        layout.addLayout(service_layout)
        
        # 서비스 설정
        service_group = QGroupBox("서비스 설정")
        service_group.setSizePolicy(_size_policy_preferred_maximum())
        service_form = QFormLayout()
        
        self.service_name_edit = QLineEdit()
        self.service_name_edit.setPlaceholderText("서비스 이름 (예: daum_maps)")
        service_form.addRow("서비스 이름:", self.service_name_edit)
        
        self.layer_name_edit = QLineEdit()
        self.layer_name_edit.setPlaceholderText("레이어 이름 (예: street)")
        service_form.addRow("레이어 이름:", self.layer_name_edit)
        
        service_group.setLayout(service_form)
        layout.addWidget(service_group)

        # 타일 URL 게이트웨이 (QGIS/브라우저가 요청하는 최종 타일 주소에만 적용, JSON 원본은 그대로)
        gw_group = QGroupBox("타일 URL 게이트웨이 (선택)")
        gw_group.setSizePolicy(_size_policy_preferred_maximum())
        gw_outer = QVBoxLayout()
        gw_outer.setSpacing(6)
        gw_help = QLabel(
            "내부망 등에서 <b>지정 URL·리버스 프록시</b>를 거쳐야 타일을 받을 때 사용합니다. "
            "아래에 넣은 값은 <b>저장된 타일 URL 앞/템플릿</b>에만 붙고, 이 화면의 URL 입력란에는 그대로 표시됩니다. "
            "<code>{z}</code>·<code>${z}</code> 같은 자리 표시자가 있는 경우 <b>URL 인코딩은 끄는 것</b>을 권장합니다(끄면 접두사+원문 그대로)."
        )
        gw_help.setWordWrap(True)
        gw_help.setTextFormat(_qt_text_format_rich())
        _gf = gw_help.font()
        _gf.setPointSize(max(_gf.pointSize() - 1, 8))
        gw_help.setFont(_gf)
        gw_help.setStyleSheet("color: palette(mid);")
        gw_outer.addWidget(gw_help)
        self.tile_gw_enable = QCheckBox("게이트웨이 사용")
        gw_outer.addWidget(self.tile_gw_enable)
        gw_mode_row = QHBoxLayout()
        gw_mode_row.addWidget(QLabel("방식:"))
        self.tile_gw_mode = QComboBox()
        self.tile_gw_mode.addItem("사용 안 함", "none")
        self.tile_gw_mode.addItem("접두사 (원본 URL 문자열 앞에 붙임)", "prefix")
        self.tile_gw_mode.addItem("템플릿 ({url} 또는 {target_url}에 원본 삽입)", "template")
        self.tile_gw_mode.currentIndexChanged.connect(self._on_tile_gw_mode_changed)
        gw_mode_row.addWidget(self.tile_gw_mode, 1)
        gw_outer.addLayout(gw_mode_row)
        self.tile_gw_prefix = QLineEdit()
        self.tile_gw_prefix.setPlaceholderText("예: https://intranet.example.com/map-proxy?target=")
        gw_outer.addWidget(QLabel("접두사:"))
        gw_outer.addWidget(self.tile_gw_prefix)
        self.tile_gw_template = QLineEdit()
        self.tile_gw_template.setPlaceholderText("예: https://intranet.example.com/tile?u={url}")
        gw_outer.addWidget(QLabel("템플릿:"))
        gw_outer.addWidget(self.tile_gw_template)
        self.tile_gw_encode = QCheckBox("원본 URL을 퍼센트 인코딩 후 삽입 ({z} 등이 있으면 끄세요)")
        gw_outer.addWidget(self.tile_gw_encode)
        self.tile_gw_enable.toggled.connect(self._on_tile_gw_enable_toggled)
        gw_group.setLayout(gw_outer)
        layout.addWidget(gw_group)

        # URL 설정
        url_group = QGroupBox("URL 설정")
        url_group.setSizePolicy(_size_policy_preferred_maximum())
        url_layout = QVBoxLayout()
        url_layout.setContentsMargins(8, 6, 8, 6)
        url_layout.setSpacing(4)

        url_help = QLabel(
            "타일 서버 주소입니다. 한 줄에 URL 하나(여러 줄이면 호스트를 순서대로 돌려 씁니다). "
            "<code>{z}</code>·<code>{x}</code>·<code>{y}</code> 또는 <code>${z}</code> 형 자리 표시자로 "
            "줌·열·행을 넣습니다. OpenLayers용으로 내부에서 순서를 맞추는 경우가 있습니다. "
            "「최신 URL 가져오기」로 갱신하면 이 값이 바뀝니다."
        )
        url_help.setWordWrap(True)
        url_help.setTextFormat(_qt_text_format_rich())
        _hf = url_help.font()
        _hf.setPointSize(max(_hf.pointSize() - 1, 8))
        url_help.setFont(_hf)
        url_help.setStyleSheet("color: palette(mid);")
        url_layout.addWidget(url_help)

        self.url_edit = QTextEdit()
        self.url_edit.setPlaceholderText(
            "예: http://mts.daumcdn.net/.../latest/{z}/{x}/{y}.png\n"
            "예: https://map.pstatic.net/nrb/styles/basic/…/${z}/${x}/${y}.jpg"
        )
        self.url_edit.setMinimumHeight(56)
        self.url_edit.setMaximumHeight(72)
        self.url_edit.setSizePolicy(_size_policy_expanding_fixed())
        url_layout.addWidget(self.url_edit)

        url_group.setLayout(url_layout)
        layout.addWidget(url_group)

        # Attribution 설정
        attr_group = QGroupBox("Attribution 설정")
        attr_group.setSizePolicy(_size_policy_preferred_maximum())
        attr_layout = QVBoxLayout()
        attr_layout.setContentsMargins(8, 6, 8, 6)
        attr_layout.setSpacing(4)

        attr_help = QLabel(
            "지도에 표시할 <b>출처·저작권</b> 안내입니다. HTML을 넣을 수 있습니다(링크·작은 로고 등). "
            "서비스 약관상 표기가 필요하면 비우지 않는 것을 권장합니다."
        )
        attr_help.setWordWrap(True)
        attr_help.setTextFormat(_qt_text_format_rich())
        _af = attr_help.font()
        _af.setPointSize(max(_af.pointSize() - 1, 8))
        attr_help.setFont(_af)
        attr_help.setStyleSheet("color: palette(mid);")
        attr_layout.addWidget(attr_help)

        self.attribution_edit = QTextEdit()
        self.attribution_edit.setPlaceholderText("HTML 형태의 attribution")
        self.attribution_edit.setMinimumHeight(56)
        self.attribution_edit.setMaximumHeight(80)
        self.attribution_edit.setSizePolicy(_size_policy_expanding_fixed())
        attr_layout.addWidget(self.attribution_edit)

        attr_group.setLayout(attr_layout)
        layout.addWidget(attr_group)

        # 버전 설정
        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("버전:"))
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("버전 정보 (예: v11_hdwvr, 1753418091)")
        version_layout.addWidget(self.version_edit)
        layout.addLayout(version_layout)

        settings_widget.setLayout(layout)
        settings_widget.setSizePolicy(_size_policy_preferred_maximum())
        settings_widget.setMinimumWidth(720)

        settings_scroll = QScrollArea()
        settings_scroll.setWidget(settings_widget)
        settings_scroll.setWidgetResizable(True)
        try:
            settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        except AttributeError:
            settings_scroll.setFrameShape(QFrame.NoFrame)
        try:
            settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except AttributeError:
            settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tab_widget.addTab(settings_scroll, "서비스 설정")
    
    def _create_proxy_group(self, parent_layout):
        """최신 URL/가용성 테스트용 HTTP 프록시(이 탭의 요청만)."""
        box = QGroupBox("프록시 (이 탭의 HTTP만 — 지도 타일 아님)")
        outer = QVBoxLayout()
        notice = QLabel(
            "QGIS 지도 캔버스의 타일에는 적용되지 않습니다. "
            "「모든 서비스 업데이트」「URL 가용성 테스트」로 나가는 요청에만 사용됩니다."
        )
        notice.setWordWrap(True)
        outer.addWidget(notice)
        self.proxy_enable_check = QCheckBox("프록시 사용")
        self.proxy_enable_check.toggled.connect(self._on_proxy_enable_toggled)
        outer.addWidget(self.proxy_enable_check)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("방식:"))
        self.proxy_mode_combo = QComboBox()
        self.proxy_mode_combo.addItem("HTTP 프록시 (IP·호스트:포트)")
        self.proxy_mode_combo.setItemData(0, "http_host", _qt_item_data_user_role())
        self.proxy_mode_combo.addItem("URL GET (템플릿에 원본 URL 삽입)")
        self.proxy_mode_combo.setItemData(1, "url_get", _qt_item_data_user_role())
        self.proxy_mode_combo.currentIndexChanged.connect(self._on_proxy_mode_changed)
        mode_row.addWidget(self.proxy_mode_combo)
        mode_row.addStretch()
        outer.addLayout(mode_row)
        self.proxy_stack = QStackedWidget()
        page_host = QWidget()
        host_form = QFormLayout()
        self.proxy_host_edit = QLineEdit()
        self.proxy_host_edit.setPlaceholderText("예: 192.168.0.1 또는 proxy.example.com")
        self.proxy_host_edit.setMinimumHeight(26)
        host_form.addRow("호스트:", self.proxy_host_edit)
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(1, 65535)
        self.proxy_port_spin.setValue(8080)
        host_form.addRow("포트:", self.proxy_port_spin)
        self.proxy_user_edit = QLineEdit()
        self.proxy_user_edit.setPlaceholderText("선택")
        self.proxy_user_edit.setMinimumHeight(26)
        host_form.addRow("사용자명:", self.proxy_user_edit)
        self.proxy_pass_edit = QLineEdit()
        _pw = getattr(QLineEdit, "Password", None)
        if _pw is None and hasattr(QLineEdit, "EchoMode"):
            _pw = getattr(QLineEdit.EchoMode, "Password", None)
        self.proxy_pass_edit.setEchoMode(_pw if _pw is not None else 2)
        self.proxy_pass_edit.setPlaceholderText("선택")
        self.proxy_pass_edit.setMinimumHeight(26)
        host_form.addRow("비밀번호:", self.proxy_pass_edit)
        page_host.setLayout(host_form)
        self.proxy_stack.addWidget(page_host)
        page_url = QWidget()
        url_form = QVBoxLayout()
        hint = QLabel(
            "원본 요청 URL이 인코딩되어 들어갑니다. 플레이스홀더: <b>{url}</b> 또는 <b>{target_url}</b><br>"
            "예: <code>http://내부게이트/proxy?target={url}</code> · <code>https://api.example.com/fetch?u={target_url}</code>"
        )
        hint.setWordWrap(True)
        hint.setTextFormat(_qt_text_format_rich())
        url_form.addWidget(hint)
        self.proxy_url_get_edit = QLineEdit()
        self.proxy_url_get_edit.setPlaceholderText("http://프록시서버/경로?target={url}")
        self.proxy_url_get_edit.setMinimumHeight(26)
        url_form.addWidget(self.proxy_url_get_edit)
        page_url.setLayout(url_form)
        self.proxy_stack.addWidget(page_url)
        outer.addWidget(self.proxy_stack)
        box.setLayout(outer)
        parent_layout.addWidget(box)

    def _on_proxy_enable_toggled(self, on):
        self.proxy_mode_combo.setEnabled(on)
        self.proxy_stack.setEnabled(on)

    def _on_proxy_mode_changed(self, _index):
        data = self.proxy_mode_combo.currentData()
        if data == "url_get":
            self.proxy_stack.setCurrentIndex(1)
        else:
            self.proxy_stack.setCurrentIndex(0)

    def _read_proxy_config_from_ui(self):
        idx = self.proxy_mode_combo.currentIndex()
        mode = self.proxy_mode_combo.itemData(idx, _qt_item_data_user_role())
        if mode is None:
            mode = "http_host" if idx == 0 else "url_get"
        return {
            "enabled": self.proxy_enable_check.isChecked(),
            "mode": mode,
            "http_host": self.proxy_host_edit.text().strip(),
            "http_port": int(self.proxy_port_spin.value()),
            "http_user": self.proxy_user_edit.text().strip(),
            "http_password": self.proxy_pass_edit.text(),
            "url_get_template": self.proxy_url_get_edit.text().strip(),
        }

    def _apply_proxy_config_to_ui(self):
        cfg = self.service_manager.get_proxy_config()
        self.proxy_enable_check.setChecked(bool(cfg.get("enabled")))
        mode = cfg.get("mode") or "http_host"
        idx = 1 if mode == "url_get" else 0
        self.proxy_mode_combo.setCurrentIndex(idx)
        self.proxy_host_edit.setText(str(cfg.get("http_host") or ""))
        try:
            self.proxy_port_spin.setValue(int(cfg.get("http_port") or 8080))
        except (TypeError, ValueError):
            self.proxy_port_spin.setValue(8080)
        self.proxy_user_edit.setText(str(cfg.get("http_user") or ""))
        self.proxy_pass_edit.setText(str(cfg.get("http_password") or ""))
        self.proxy_url_get_edit.setText(str(cfg.get("url_get_template") or ""))
        self._on_proxy_mode_changed(0)
        self._on_proxy_enable_toggled(self.proxy_enable_check.isChecked())

    def _on_tile_gw_enable_toggled(self, on):
        self.tile_gw_mode.setEnabled(on)
        self.tile_gw_encode.setEnabled(on)
        if not on:
            self.tile_gw_prefix.setEnabled(False)
            self.tile_gw_template.setEnabled(False)
        else:
            self._on_tile_gw_mode_changed(self.tile_gw_mode.currentIndex())

    def _on_tile_gw_mode_changed(self, _index):
        if not self.tile_gw_enable.isChecked():
            return
        mode = self.tile_gw_mode.currentData()
        if mode is None:
            mode = "none"
        if mode == "prefix":
            self.tile_gw_prefix.setEnabled(True)
            self.tile_gw_template.setEnabled(False)
        elif mode == "template":
            self.tile_gw_prefix.setEnabled(False)
            self.tile_gw_template.setEnabled(True)
        else:
            self.tile_gw_prefix.setEnabled(False)
            self.tile_gw_template.setEnabled(False)

    def _apply_tile_gateway_to_ui(self):
        cfg = self.service_manager.get_tile_gateway_config()
        self.tile_gw_enable.setChecked(bool(cfg.get("enabled")))
        mode = (cfg.get("mode") or "none").lower()
        idx = 0
        for i in range(self.tile_gw_mode.count()):
            d = self.tile_gw_mode.itemData(i, _qt_item_data_user_role())
            if d is not None and str(d).lower() == mode:
                idx = i
                break
        self.tile_gw_mode.setCurrentIndex(idx)
        self.tile_gw_prefix.setText(str(cfg.get("prefix") or ""))
        self.tile_gw_template.setText(str(cfg.get("template") or ""))
        self.tile_gw_encode.setChecked(bool(cfg.get("encode_target")))
        self._on_tile_gw_enable_toggled(self.tile_gw_enable.isChecked())

    def _read_tile_gateway_from_ui(self):
        mode = self.tile_gw_mode.currentData()
        if mode is None:
            mode = "none"
        return {
            "enabled": self.tile_gw_enable.isChecked(),
            "mode": str(mode).lower(),
            "prefix": self.tile_gw_prefix.text().strip(),
            "template": self.tile_gw_template.text().strip(),
            "encode_target": self.tile_gw_encode.isChecked(),
        }

    def _read_api_config_from_ui(self):
        return {
            "kakao_sdk_key": self.kakao_api_key_edit.text().strip(),
        }

    def _apply_api_config_to_ui(self):
        cfg = self.service_manager.get_api_config()
        self.kakao_api_key_edit.setText(str(cfg.get("kakao_sdk_key") or ""))
        self._on_kakao_key_changed(self.kakao_api_key_edit.text())

    def _on_kakao_key_changed(self, text):
        if not hasattr(self, "kakao_check"):
            return
        has_key = bool((text or "").strip())
        self.kakao_check.setEnabled(has_key)
        if has_key:
            self.kakao_check.setToolTip("")
            if not self.kakao_check.isChecked():
                self.kakao_check.setChecked(True)
        else:
            self.kakao_check.setChecked(False)
            self.kakao_check.setToolTip("카카오 SDK 키를 입력하면 활성화됩니다.")

    def create_url_update_tab(self):
        """최신 URL 가져오기 탭 생성"""
        update_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # 설명
        info_label = QLabel("지도 서비스의 최신 URL을 자동으로 가져와서 설정을 업데이트합니다.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._create_proxy_group(layout)

        api_group = QGroupBox("API 키 (최신 URL 가져오기용)")
        api_layout = QFormLayout()
        self.kakao_api_key_edit = QLineEdit()
        self.kakao_api_key_edit.setPlaceholderText("카카오 JavaScript SDK appkey 입력")
        self.kakao_api_key_edit.setMinimumHeight(26)
        self.kakao_api_key_edit.textChanged.connect(self._on_kakao_key_changed)
        api_help = QLabel(
            "카카오 최신 URL 갱신 시 SDK 스크립트 요청에 사용합니다. "
            "미입력 시 카카오 업데이트는 비활성화됩니다."
        )
        api_help.setWordWrap(True)
        api_layout.addRow("Kakao SDK Key:", self.kakao_api_key_edit)
        api_layout.addRow("", api_help)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        # 서비스 선택
        service_select_layout = QHBoxLayout()
        service_select_layout.addWidget(QLabel("업데이트할 서비스:"))
        
        self.kakao_check = QCheckBox("카카오 지도")
        self.kakao_check.setChecked(False)
        self.kakao_check.setEnabled(False)
        self.kakao_check.setToolTip("카카오 SDK 키를 입력하면 활성화됩니다.")
        self.naver_check = QCheckBox("네이버 지도")
        self.naver_check.setChecked(True)
        self.vworld_check = QCheckBox("VWorld")
        self.vworld_check.setChecked(True)
        
        service_select_layout.addWidget(self.kakao_check)
        service_select_layout.addWidget(self.naver_check)
        service_select_layout.addWidget(self.vworld_check)
        service_select_layout.addStretch()
        
        layout.addLayout(service_select_layout)
        
        # 업데이트 버튼
        update_button_layout = QHBoxLayout()
        self.update_all_btn = QPushButton("모든 서비스 업데이트")
        self.update_all_btn.clicked.connect(self.update_all_services)
        self.test_urls_btn = QPushButton("URL 가용성 테스트")
        self.test_urls_btn.clicked.connect(self.test_urls)
        
        update_button_layout.addWidget(self.update_all_btn)
        update_button_layout.addWidget(self.test_urls_btn)
        update_button_layout.addStretch()
        
        layout.addLayout(update_button_layout)
        
        # 진행 상황
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 결과 표시
        result_group = QGroupBox("진행 로그")
        result_layout = QVBoxLayout()
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(300)
        result_layout.addWidget(self.result_text)
        
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)
        
        update_widget.setLayout(layout)
        update_widget.setMinimumWidth(720)
        update_widget.setSizePolicy(_size_policy_preferred_maximum())

        update_scroll = QScrollArea()
        update_scroll.setWidget(update_widget)
        update_scroll.setWidgetResizable(True)
        try:
            update_scroll.setFrameShape(QFrame.Shape.NoFrame)
        except AttributeError:
            update_scroll.setFrameShape(QFrame.NoFrame)
        try:
            update_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            update_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except AttributeError:
            update_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            update_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tab_widget.addTab(update_scroll, "최신 URL 가져오기")
    
    def load_config(self):
        """설정 파일 로드"""
        try:
            self.service_manager.reload_config()
            service_names = self.service_manager.get_map_service_names()
            self.service_combo.clear()
            
            for service_name in service_names:
                self.service_combo.addItem(service_name)
            
            if self.service_combo.count() > 0:
                self.service_combo.setCurrentIndex(0)
                self.on_service_changed(self.service_combo.currentText())
            self._apply_proxy_config_to_ui()
            self._apply_tile_gateway_to_ui()
            self._apply_api_config_to_ui()

        except Exception as e:
            QgsMessageLog.logMessage(f"설정 로드 실패: {str(e)}", "TMS for Korea")
    
    def on_service_changed(self, service_name):
        """서비스 변경 시 호출"""
        if not service_name:
            return
        
        try:
            service_data = self.service_manager.get_service(service_name)
            if service_data:
                self.layer_combo.blockSignals(True)
                self.layer_combo.clear()
                for layer_name in self.service_manager.get_service_layers(service_name):
                    self.layer_combo.addItem(layer_name)
                if self.layer_combo.count() > 0:
                    self.layer_combo.setCurrentIndex(0)
                self.layer_combo.blockSignals(False)
                self._apply_layer_selection_to_form()
        
        except Exception as e:
            QgsMessageLog.logMessage(f"서비스 정보 로드 실패: {str(e)}", "TMS for Korea")
    
    def on_layer_changed(self, layer_name):
        """레이어 변경 시 호출 (콤보 텍스트 시그널)"""
        self._apply_layer_selection_to_form()

    def _on_layer_index_changed(self, index):
        """currentTextChanged가 생략되는 경우 대비(동일 인덱스 재설정 등)."""
        if index < 0:
            return
        self._apply_layer_selection_to_form()

    def _apply_layer_selection_to_form(self):
        """현재 서비스/레이어 콤보 선택에 맞춰 폼(URL·버전 등) 갱신."""
        service_name = self.service_combo.currentText()
        layer_name = self.layer_combo.currentText()
        if not service_name or not layer_name:
            self.version_edit.clear()
            return
        try:
            service_data = self.service_manager.get_service(service_name)
            if not service_data:
                self.url_edit.clear()
                self.attribution_edit.clear()
                self.version_edit.clear()
                return
            layer_data = service_data.get(layer_name)
            if not isinstance(layer_data, dict):
                self.url_edit.clear()
                self.attribution_edit.clear()
                self.version_edit.clear()
                return
            self.service_name_edit.setText(service_name)
            self.layer_name_edit.setText(layer_name)
            urls = layer_data.get('urls', [])
            self.url_edit.setPlainText('\n'.join(urls))
            self.attribution_edit.setPlainText(layer_data.get('attribution', ''))
            parsed_ver = _tile_version_from_urls(urls)
            if parsed_ver is not None:
                self.version_edit.setText(parsed_ver)
            else:
                ver = layer_data.get('version', '')
                self.version_edit.setText("" if ver is None else str(ver))
        except Exception as e:
            QgsMessageLog.logMessage(f"레이어 정보 로드 실패: {str(e)}", "TMS for Korea")
    
    def add_service(self):
        """새 서비스 추가"""
        service_name = self.service_name_edit.text().strip()
        layer_name = self.layer_name_edit.text().strip()
        
        if service_name.startswith("_"):
            QMessageBox.warning(self, "경고", "서비스 이름은 '_'로 시작할 수 없습니다.")
            return
        
        if not service_name or not layer_name:
            QMessageBox.warning(self, "경고", "서비스 이름과 레이어 이름을 입력하세요.")
            return
        
        try:
            urls = [url.strip() for url in self.url_edit.toPlainText().split('\n') if url.strip()]
            attribution = self.attribution_edit.toPlainText().strip()
            version = self.version_edit.text().strip()
            
            # 서비스 추가
            self.service_manager.add_service(service_name, layer_name, urls, attribution, version)
            self.service_manager.save_config()
            
            # 콤보박스 업데이트
            if self.service_combo.findText(service_name) == -1:
                self.service_combo.addItem(service_name)
            
            self.service_combo.setCurrentText(service_name)
            
            QMessageBox.information(self, "성공", "서비스가 추가되었습니다.")
        
        except Exception as e:
            QMessageBox.critical(self, "오류", f"서비스 추가 실패: {str(e)}")
    
    def remove_service(self):
        """서비스 삭제"""
        service_name = self.service_combo.currentText()
        if not service_name:
            return
        
        reply = QMessageBox.question(self, "확인", 
                                   f"'{service_name}' 서비스를 삭제하시겠습니까?",
                                   _msgbox_button("Yes") | _msgbox_button("No"))
        
        if reply == _msgbox_button("Yes"):
            try:
                self.service_manager.remove_service(service_name)
                
                # 콤보박스에서 제거
                index = self.service_combo.findText(service_name)
                if index >= 0:
                    self.service_combo.removeItem(index)
                
                QMessageBox.information(self, "성공", "서비스가 삭제되었습니다.")
            
            except Exception as e:
                QMessageBox.critical(self, "오류", f"서비스 삭제 실패: {str(e)}")
    
    def save_config(self):
        """설정 저장 — 현재 선택 레이어 + 타일 게이트웨이 + 프록시 + API 키를 JSON에 기록."""
        try:
            service_name = self.service_combo.currentText()
            layer_name = self.layer_combo.currentText()
            if service_name and layer_name:
                urls = [u.strip() for u in self.url_edit.toPlainText().split('\n') if u.strip()]
                if not urls:
                    QMessageBox.warning(self, "경고", "URL을 한 줄 이상 입력해야 저장할 수 있습니다.")
                    return
                attribution = self.attribution_edit.toPlainText()
                version = self.version_edit.text().strip()
                self.service_manager.update_service(
                    service_name, layer_name, urls, attribution, version
                )
            self.service_manager.merge_tile_gateway_config(self._read_tile_gateway_from_ui())
            self.service_manager.merge_api_config(self._read_api_config_from_ui())
            self.service_manager.set_proxy_config(self._read_proxy_config_from_ui())
            self.configUpdated.emit()
            QMessageBox.information(self, "성공", "설정이 저장되었습니다.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "오류", f"설정 저장 실패: {str(e)}")
    
    def update_all_services(self):
        """모든 서비스 업데이트"""
        include_services = {
            "kakao": self.kakao_check.isChecked(),
            "naver": self.naver_check.isChecked(),
            "vworld": self.vworld_check.isChecked(),
        }
        if include_services["kakao"] and not self.kakao_api_key_edit.text().strip():
            QMessageBox.warning(self, "경고", "카카오 SDK 키를 입력해야 카카오 업데이트를 실행할 수 있습니다.")
            return
        if not any(include_services.values()):
            QMessageBox.warning(self, "경고", "업데이트할 서비스를 하나 이상 선택하세요.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 무한 진행바
        
        # 워커 스레드 생성 및 시작
        self.update_worker = URLUpdateWorker(
            self.url_updater,
            self._read_proxy_config_from_ui(),
            include_services=include_services,
            kakao_api_key=self.kakao_api_key_edit.text(),
        )
        self.update_worker.update_progress.connect(self.on_update_progress)
        self.update_worker.update_finished.connect(self.on_update_finished)
        self.update_worker.update_error.connect(self.on_update_error)
        self.update_worker.start()
    
    def on_update_progress(self, message):
        """업데이트 진행 상황"""
        self.result_text.append(f"[진행] {message}")
        QApplication.processEvents()
    
    def on_update_finished(self, results):
        """업데이트 완료"""
        self.progress_bar.setVisible(False)
        self.result_text.clear()
        
        success_count = 0
        for service_name, result in results.items():
            status = result.get('status', 'error')
            message = result.get('message', '알 수 없는 오류')
            
            # 네이버의 경우 각 레이어별로 개별 처리
            if service_name == 'naver' and isinstance(result, dict):
                # 네이버는 각 레이어 타입별로 개별 업데이트
                for layer_type, layer_result in result.items():
                    layer_status = layer_result.get('status', 'error')
                    layer_message = layer_result.get('message', '알 수 없는 오류')
                    
                    if layer_status == 'success':
                        success_count += 1
                        self.result_text.append(f"✅ {service_name} {layer_type}: {layer_message}")
                    elif layer_status == 'fallback':
                        self.result_text.append(f"⚠️ {service_name} {layer_type}: {layer_message}")
                    else:
                        self.result_text.append(f"❌ {service_name} {layer_type}: {layer_message}")
                
                # 네이버 설정에 반영 - result 파라미터 전달
                self.apply_update_result('naver_maps', result=result)
                continue  # 네이버 처리가 완료되었으므로 다음 서비스로 넘어감
                
            # 카카오의 경우 각 레이어별로 개별 처리
            elif service_name == 'kakao' and isinstance(result, dict):
                # 카카오는 각 레이어 타입별로 개별 업데이트
                for layer_type, layer_result in result.items():
                    layer_status = layer_result.get('status', 'error')
                    layer_message = layer_result.get('message', '알 수 없는 오류')
                    
                    if layer_status == 'success':
                        success_count += 1
                        self.result_text.append(f"✅ {service_name} {layer_type}: {layer_message}")
                    elif layer_status == 'fallback':
                        self.result_text.append(f"⚠️ {service_name} {layer_type}: {layer_message}")
                    else:
                        self.result_text.append(f"❌ {service_name} {layer_type}: {layer_message}")
                
                # 카카오 설정에 반영 - result 파라미터 전달
                self.apply_update_result('daum_maps', result=result)
                continue  # 카카오 처리가 완료되었으므로 다음 서비스로 넘어감
                
            elif status == 'success':
                success_count += 1
                self.result_text.append(f"✅ {service_name}: {message}")
                
                # 설정에 반영
                if service_name == 'vworld':
                    self.apply_update_result('vworld_maps', 'street', result)
            
            elif status == 'fallback':
                self.result_text.append(f"⚠️ {service_name}: {message}")
                
                # fallback도 설정에 반영 (VWorld의 경우)
                if service_name == 'vworld':
                    self.apply_update_result('vworld_maps', 'street', result)
            else:
                self.result_text.append(f"❌ {service_name}: {message}")
        
        self.result_text.append(f"\n총 {len(results)}개 서비스 중 {success_count}개 업데이트 완료")
        
        # 서비스 설정 탭 데이터 업데이트
        self.refresh_settings_tab()
    
    def on_update_error(self, error_message):
        """업데이트 오류"""
        self.progress_bar.setVisible(False)
        self.result_text.append(f"❌ 오류: {error_message}")
    
    def apply_update_result(self, service_name, layer_name=None, result=None):
        """업데이트 결과를 설정에 적용"""
        try:
            # 네이버의 경우 각 레이어별로 개별 처리
            if service_name == 'naver_maps' and isinstance(result, dict):
                # 네이버는 각 레이어 타입별로 개별 업데이트
                for layer_type, layer_result in result.items():
                    urls = layer_result.get('urls', [])
                    attribution = layer_result.get('attribution', '')
                    version = layer_result.get('version', '')
                    
                    if urls:
                        # 기존 서비스가 있으면 업데이트, 없으면 추가
                        if self.service_manager.has_service('naver_maps'):
                            self.service_manager.update_service('naver_maps', layer_type, urls, attribution, version)
                        else:
                            self.service_manager.add_service('naver_maps', layer_type, urls, attribution, version)
                
                self.result_text.append(f"✅ {service_name}: 각 레이어별 개별 업데이트 완료")
                
            # 카카오의 경우 각 레이어별로 개별 처리
            elif service_name == 'daum_maps' and isinstance(result, dict):
                # 카카오는 각 레이어 타입별로 개별 업데이트 (네이버와 동일한 방식)
                for layer_type, layer_result in result.items():
                    urls = layer_result.get('urls', [])
                    attribution = layer_result.get('attribution', '')
                    version = layer_result.get('version', '')
                    
                    if urls:
                        # 기존 서비스가 있으면 업데이트, 없으면 추가
                        if self.service_manager.has_service('daum_maps'):
                            self.service_manager.update_service('daum_maps', layer_type, urls, attribution, version)
                        else:
                            self.service_manager.add_service('daum_maps', layer_type, urls, attribution, version)
                
                self.result_text.append(f"✅ {service_name}: 각 레이어별 개별 업데이트 완료")
                
            else:
                # VWorld 등은 기존 방식
                urls = result.get('urls', [])
                attribution = result.get('attribution', '')
                version = result.get('version', '')
                
                if not urls:
                    self.result_text.append(f"⚠️ {service_name}: URL이 비어있어 업데이트를 건너뜁니다.")
                    return
                
                # 기존 서비스가 있으면 업데이트, 없으면 추가
                if self.service_manager.has_service(service_name):
                    service_data = self.service_manager.get_service(service_name)
                    # VWorld URL 최신화는 Base(street)만 오므로 layer_name이 있으면 해당 레이어만 갱신
                    if layer_name and layer_name in service_data:
                        self.service_manager.update_service(
                            service_name, layer_name, urls, attribution, version
                        )
                        self.result_text.append(
                            f"✅ {service_name}/{layer_name}: 업데이트 완료 (버전: {version})"
                        )
                    elif layer_name:
                        self.result_text.append(
                            f"⚠️ {service_name}: 레이어 '{layer_name}' 없음, URL 업데이트 건너뜀"
                        )
                    else:
                        for existing_layer in service_data.keys():
                            self.service_manager.update_service(
                                service_name, existing_layer, urls, attribution, version
                            )
                        self.result_text.append(
                            f"✅ {service_name}: 기존 서비스 업데이트 완료 (버전: {version})"
                        )
                else:
                    # 새 서비스 추가
                    self.service_manager.add_service(service_name, layer_name, urls, attribution, version)
                    self.result_text.append(f"✅ {service_name}: 새 서비스 추가 완료 (버전: {version})")
            
            # 설정 파일 저장
            self.service_manager.save_config()
        
        except Exception as e:
            self.result_text.append(f"❌ {service_name} 설정 적용 실패: {str(e)}")
            QgsMessageLog.logMessage(f"설정 적용 실패: {str(e)}", "TMS for Korea")
    
    def test_urls(self):
        """URL 가용성 테스트"""
        try:
            self.url_updater.configure_proxies(self._read_proxy_config_from_ui())
            # 현재 선택된 서비스의 URL들 테스트
            service_name = self.service_combo.currentText()
            if not service_name:
                QMessageBox.warning(self, "경고", "테스트할 서비스를 선택하세요.")
                return
            
            service_data = self.service_manager.get_service(service_name)
            if not service_data:
                return
            
            # 모든 URL 수집
            all_urls = []
            for layer_data in service_data.values():
                for u in layer_data.get("urls", []):
                    all_urls.append(self.service_manager.wrap_tile_url(u))
            
            if not all_urls:
                QMessageBox.warning(self, "경고", "테스트할 URL이 없습니다.")
                return
            
            test_results = self.url_updater.test_url_availability(all_urls, user_probe=None)

            self.result_text.append("\n[URL 가용성 테스트]")
            ok_count = 0
            for result in test_results:
                url = result.get("url", "")
                detail = result.get("detail") or result.get("error") or "상태 코드: %s" % result.get("status_code", "N/A")
                if result.get("available", False):
                    ok_count += 1
                    self.result_text.append(f"✅ {url} - {detail}")
                else:
                    self.result_text.append(f"❌ {url} - {detail}")
            self.result_text.append(f"[요약] {len(test_results)}개 중 {ok_count}개 사용 가능")
            
            QMessageBox.information(self, "완료", f"{len(test_results)}개 URL 테스트 완료")
        
        except Exception as e:
            QMessageBox.critical(self, "오류", f"URL 테스트 실패: {str(e)}") 

    def refresh_settings_tab(self):
        """서비스 설정 탭 데이터 새로고침"""
        try:
            # 현재 선택된 서비스와 레이어 저장
            current_service = self.service_combo.currentText()
            current_layer = self.layer_combo.currentText() if self.layer_combo.count() > 0 else ""
            
            # 설정 다시 로드
            self.load_config()
            
            # 이전 선택 상태 복원
            if current_service:
                index = self.service_combo.findText(current_service)
                if index >= 0:
                    self.service_combo.setCurrentIndex(index)
                    
                    # 레이어 선택도 복원
                    if current_layer:
                        layer_index = self.layer_combo.findText(current_layer)
                        if layer_index >= 0:
                            self.layer_combo.setCurrentIndex(layer_index)
            self._apply_layer_selection_to_form()
            
            self.result_text.append("🔄 서비스 설정 탭 데이터가 업데이트되었습니다.")
            
        except Exception as e:
            self.result_text.append(f"⚠️ 설정 탭 업데이트 실패: {str(e)}")
            QgsMessageLog.logMessage(f"설정 탭 업데이트 실패: {str(e)}", "TMS for Korea") 