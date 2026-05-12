# -*- coding: utf-8 -*-
"""
/***************************************************************************
OpenLayers Plugin
A QGIS plugin

                             -------------------
begin                : 2010-02-03
copyright            : (C) 2010 by Pirmin Kalberer, Sourcepole
email                : pka at sourcepole.ch
modified             : 2018-11-23 by Minpa Lee, mapplus at gmail.com
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

from qgis.PyQt.QtCore import (QUrl, Qt, QMetaObject, QTimer, QEventLoop,
                              QSize, QObject, pyqtSignal, qDebug, pyqtSlot)
from qgis.PyQt.QtGui import QImage, QPainter
try:
    from qgis.PyQt.QtWebKitWidgets import QWebPage
    WEB_BACKEND = "webkit"
except Exception:
    QWebPage = None
    WEB_BACKEND = "webengine"
    try:
        from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
    except Exception:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    try:
        from qgis.PyQt.QtWebEngineCore import QWebEngineSettings
    except Exception:
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineSettings
        except Exception:
            from PyQt6.QtWebEngineCore import QWebEngineSettings
    try:
        from qgis.PyQt.QtWebEngineWidgets import QWebEnginePage
    except Exception:
        try:
            from qgis.PyQt.QtWebEngineCore import QWebEnginePage
        except Exception:
            from PyQt6.QtWebEngineCore import QWebEnginePage
from qgis.core import (QgsMapLayerRenderer, Qgis, QgsMessageLog,
                       QgsPluginLayer, QgsRectangle)

import math
import os
import datetime
import time

debuglevel = 0  # 0: 로그/파일 없음. 1+: 파일 로그, verbosity 이상일 때 qDebug
DEBUG_LOG_PATH = os.path.join(os.path.expanduser("~"), "Documents", "tmsforkorea_debug.log")
DEBUG_IMAGE_PATH = os.path.join(os.path.expanduser("~"), "Documents", "tmsforkorea_last_render.png")
DEBUG_SAVE_RENDER_IMAGE = False

# WebEngine: QGIS3(WebKit) 체감에 맞추기 — 폴링/상한은 WebKit과 동일, 캡처는 타일 붙을 시간 조금 확보
WEBENGINE_SETTLE_BEFORE_CAPTURE_MS = 80
WEBENGINE_PARTIAL_RENDER_AFTER_SEC = 0.62
WEBENGINE_MAP_LOAD_TIMEOUT_MS = 2500
WEBENGINE_POLL_MAP_MS = 100
WEBENGINE_JS_EVAL_TIMEOUT_MS = 2600
LEGACY_PARTIAL_RENDER_AFTER_SEC = 0.45
# WebKit에는 없던 ‘흰 화면 시 직전 프레임 재사용’(체감이 달라 보일 수 있음)
WEBENGINE_REUSE_LAST_GOOD_FRAME = False
WHITE_FRAME_SAMPLE_RATIO = 0.88
WHITE_FRAME_RGB_MIN = 248


def debug(msg, verbosity=1):
    if debuglevel >= 1:
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass
    if debuglevel >= verbosity:
        try:
            qDebug(msg)
        except Exception:
            pass


def _qt_enum(name, enum_type=None):
    qt = Qt
    if hasattr(qt, name):
        return getattr(qt, name)
    if enum_type and hasattr(qt, enum_type):
        enum_cls = getattr(qt, enum_type)
        if hasattr(enum_cls, name):
            return getattr(enum_cls, name)
    return None


QT_KEEP_ASPECT_RATIO = _qt_enum("KeepAspectRatio", "AspectRatioMode")
QT_SMOOTH_TRANSFORMATION = _qt_enum("SmoothTransformation", "TransformationMode")
QT_WA_DONT_SHOW_ON_SCREEN = _qt_enum("WA_DontShowOnScreen", "WidgetAttribute")
QIMAGE_ARGB32_PREMULT = getattr(QImage, "Format_ARGB32_Premultiplied", None)
if QIMAGE_ARGB32_PREMULT is None and hasattr(QImage, "Format"):
    QIMAGE_ARGB32_PREMULT = getattr(QImage.Format, "Format_ARGB32_Premultiplied", None)


def _webengine_setting_attr(name):
    if hasattr(QWebEngineSettings, name):
        return getattr(QWebEngineSettings, name)
    if hasattr(QWebEngineSettings, "WebAttribute"):
        enum_cls = QWebEngineSettings.WebAttribute
        if hasattr(enum_cls, name):
            return getattr(enum_cls, name)
    return None


def _event_loop_exec(loop):
    if hasattr(loop, "exec_"):
        return loop.exec_()
    return loop.exec()


def _is_mostly_white(img):
    """흰·준흰 화면 여부를 빠르게 판정(샘플링). 비율·RGB 하한은 상수로 조정."""
    try:
        w = img.width()
        h = img.height()
        if w <= 0 or h <= 0:
            return True
        lo = WHITE_FRAME_RGB_MIN
        xs = [int(i * (w - 1) / 9) for i in range(10)]
        ys = [int(i * (h - 1) / 9) for i in range(10)]
        white = 0
        total = 0
        for y in ys:
            for x in xs:
                c = img.pixelColor(x, y)
                total += 1
                if c.red() >= lo and c.green() >= lo and c.blue() >= lo and c.alpha() >= lo:
                    white += 1
        return total > 0 and (white / total) >= WHITE_FRAME_SAMPLE_RATIO
    except Exception:
        return False


def _qt_flag(name, enum_type=None):
    return _qt_enum(name, enum_type)


if WEB_BACKEND == "webkit":
    class OLWebPage(QWebPage):
        def __init__(self, parent=None):
            QWebPage.__init__(self, parent)

            self.loaded = False

            self.extent = None
            self.olResolutions = None

            self.lastExtent = None
            self.lastViewPortSize = None
            self.lastLogicalDpi = None
            self.lastOutputDpi = None
            self.lastMapUnitsPerPixel = None
            self.lastGoodImage = None

        def resolutions(self):
            if self.olResolutions is None:
                # get OpenLayers resolutions
                jsResolutions = self.mainFrame().evaluateJavaScript(
                    "map.layers[0].resolutions")
                debug("Detected OpenLayers resolutions: %s" % jsResolutions)
                self.olResolutions = jsResolutions
            return self.olResolutions or []

        def javaScriptConsoleMessage(self, message, lineNumber, sourceID):
            qDebug("%s[%d]: %s" % (sourceID, lineNumber, message))
else:
    class _DebugWebEnginePage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
            try:
                debug("[WebEngine JS] {}:{} {}".format(sourceID, lineNumber, message), 2)
                if debuglevel >= 2:
                    QgsMessageLog.logMessage(
                        "[WebEngine JS] {}:{} {}".format(sourceID, lineNumber, message),
                        "TMS for Korea",
                        Qgis.Warning,
                    )
            except Exception:
                pass

    class _WebEngineFrameAdapter:
        def __init__(self, view):
            self._view = view
            self._page = view.page()

        def evaluateJavaScript(self, script):
            result = {"value": None}
            loop = QEventLoop()

            def _done(value):
                result["value"] = value
                loop.quit()

            self._page.runJavaScript(script, _done)
            QTimer.singleShot(WEBENGINE_JS_EVAL_TIMEOUT_MS, loop.quit)
            _event_loop_exec(loop)
            return result["value"]

        def load(self, url):
            debug("WebEngine load url: {}".format(url.toString()), 1)
            self._view.load(url)

        def render(self, painter):
            # QtWebEngine에서는 offscreen grab()이 흰 화면으로 나오는 경우가 있어
            # QWidget.render()를 우선 시도하고 실패 시 grab()으로 폴백한다.
            try:
                self._view.render(painter)
                return
            except Exception:
                pass
            pix = self._view.grab()
            if not pix.isNull():
                painter.drawPixmap(0, 0, pix)

    class OLWebPage(QObject):
        loadFinished = pyqtSignal(bool)

        def __init__(self, parent=None):
            QObject.__init__(self, parent)
            self.loaded = False

            self.extent = None
            self.olResolutions = None

            self.lastExtent = None
            self.lastViewPortSize = None
            self.lastLogicalDpi = None
            self.lastOutputDpi = None
            self.lastMapUnitsPerPixel = None
            self.lastGoodImage = None
            self.lastGoodOlZoomIdx = None

            self._view = QWebEngineView()
            self._page = _DebugWebEnginePage(self._view)
            self._view.setPage(self._page)
            web_settings = self._view.settings()
            # Local HTML(OpenLayers)에서 원격 타일 URL 접근 허용
            for attr_name in (
                "LocalContentCanAccessRemoteUrls",
                "LocalContentCanAccessFileUrls",
                "JavascriptEnabled",
                "AllowRunningInsecureContent",
            ):
                attr = _webengine_setting_attr(attr_name)
                if attr is not None:
                    web_settings.setAttribute(attr, True)
            # 완전 offscreen 위치에서는 일부 환경에서 흰 화면만 캡처되는 문제가 있어
            # 화면 내부의 매우 작은 도구창으로 유지한다.
            tool_flag = _qt_flag("Tool", "WindowType")
            frameless_flag = _qt_flag("FramelessWindowHint", "WindowType")
            if tool_flag is not None:
                flags = tool_flag
                if frameless_flag is not None:
                    flags = flags | frameless_flag
                self._view.setWindowFlags(flags)
            self._view.setWindowOpacity(0.01)
            self._view.setGeometry(5, 5, 64, 64)
            self._view.show()
            self._view.loadFinished.connect(self.loadFinished.emit)
            self._frame = _WebEngineFrameAdapter(self._view)

        def setViewportSize(self, size):
            self._view.resize(size)

        def mainFrame(self):
            return self._frame

        def resolutions(self):
            if self.olResolutions is None:
                jsResolutions = self.mainFrame().evaluateJavaScript(
                    "map.layers[0].resolutions")
                debug("Detected OpenLayers resolutions: %s" % jsResolutions)
                self.olResolutions = jsResolutions
            return self.olResolutions or []


class OpenlayersController(QObject):
    """
    Helper class that deals with QWebPage.
    The object lives in GUI thread, its request() slot is asynchronously called
    from worker thread.
    See https://github.com/wonder-sk/qgis-mtr-example-plugin for basic example
    1. Load Web Page with OpenLayers map
    2. Update OL map extend according to QGIS canvas extent
    """

    # signal that reports to the worker thread that the image is ready
    finished = pyqtSignal()

    def __init__(self, parent, context, webPage, layerType):
        QObject.__init__(self, parent)

        debug("OpenlayersController.__init__", 3)
        self.context = context
        self.layerType = layerType

        self.img = QImage()

        self.page = webPage
        self.page.loadFinished.connect(self.pageLoaded)
        # initial size for map
        self.page.setViewportSize(QSize(1, 1))

        self.timerMapReady = QTimer()
        self.timerMapReady.setSingleShot(True)
        self.timerMapReady.setInterval(20)
        self.timerMapReady.timeout.connect(self.checkMapReady)

        self.timer = QTimer()
        self.timer.setInterval(
            WEBENGINE_POLL_MAP_MS if WEB_BACKEND == "webengine" else 100
        )
        self.timer.timeout.connect(self.checkMapUpdate)

        self.timerMax = QTimer()
        self.timerMax.setSingleShot(True)
        # WebEngine: 타일 로딩·캡처 지연이 커서 상한을 넉넉히 둔다.
        self.timerMax.setInterval(
            WEBENGINE_MAP_LOAD_TIMEOUT_MS if WEB_BACKEND == "webengine" else 2500
        )
        self.timerMax.timeout.connect(self.mapTimeout)

    @pyqtSlot()
    def request(self):
        debug("[GUI THREAD] Processing request", 3)
        debug("[GUI THREAD] request called", 1)
        self.cancelled = False

        if not self.page.loaded:
            self.init_page()
        else:
            self.setup_map()

    def init_page(self):
        url = self.layerType.html_url()
        debug("page file: %s" % url, 1)
        self.page.mainFrame().load(QUrl(url))
        # wait for page to finish loading
        debug("OpenlayersWorker waiting for page to load", 3)

    def pageLoaded(self):
        debug("[GUI THREAD] pageLoaded", 1)
        if self.cancelled:
            self.emitErrorImage()
            return

        # wait until OpenLayers map is ready
        self.checkMapReady()

    def checkMapReady(self):
        debug("[GUI THREAD] checkMapReady", 1)
        try:
            if self.page and hasattr(self.page, 'mainFrame') and self.page.mainFrame():
                if self.page.mainFrame().evaluateJavaScript("map != undefined"):
                    # map ready
                    debug("[GUI THREAD] map object detected", 1)
                    self.page.loaded = True
                    self.setup_map()
                else:
                    # wait for map
                    self.timerMapReady.start()
            else:
                # page object is no longer valid
                debug("[GUI THREAD] Page object is no longer valid", 3)
                self.emitErrorImage()
        except RuntimeError as e:
            debug(f"[GUI THREAD] RuntimeError in checkMapReady: {e}", 3)
            self.emitErrorImage()
        except Exception as e:
            debug(f"[GUI THREAD] Exception in checkMapReady: {e}", 3)
            self.emitErrorImage()

    def setup_map(self):
        debug("[GUI THREAD] setup_map begin", 1)
        rendererContext = self.context

        # FIXME: self.mapSettings.outputDpi()
        self.outputDpi = rendererContext.painter().device().logicalDpiX()
        debug(" extent: %s" % rendererContext.extent().toString(), 3)
        debug(" center: %lf, %lf" % (rendererContext.extent().center().x(),
                                     rendererContext.extent().center().y()), 3)
        debug(" size: %d, %d" % (
            rendererContext.painter().viewport().size().width(),
              rendererContext.painter().viewport().size().height()), 3)
        debug(" logicalDpiX: %d" % rendererContext.painter().
              device().logicalDpiX(), 3)
        debug(" outputDpi: %lf" % self.outputDpi)
        debug(" mapUnitsPerPixel: %f" % rendererContext.mapToPixel().
              mapUnitsPerPixel(), 3)
        # debug(" rasterScaleFactor: %s" % str(rendererContext.
        #                                      rasterScaleFactor()), 3)
        # debug(" outputSize: %d, %d" % (self.iface.mapCanvas().mapRenderer().
        #                                outputSize().width(),
        #                                self.iface.mapCanvas().mapRenderer().
        #                                outputSize().height()), 3)
        # debug(" scale: %lf" % self.iface.mapCanvas().mapRenderer().scale(),
        #                                3)
        #
        # if (self.page.lastExtent == rendererContext.extent()
        #         and self.page.lastViewPortSize == rendererContext.painter().
        #         viewport().size()
        #         and self.page.lastLogicalDpi == rendererContext.painter().
        #         device().logicalDpiX()
        #         and self.page.lastOutputDpi == self.outputDpi
        #         and self.page.lastMapUnitsPerPixel == rendererContext.
        #         mapToPixel().mapUnitsPerPixel()):
        #     self.renderMap()
        #     self.finished.emit()
        #     return

        self.targetSize = rendererContext.painter().viewport().size()
        if rendererContext.painter().device().logicalDpiX() != int(self.outputDpi):
            # use screen dpi for printing
            sizeFact = self.outputDpi / 25.4 / rendererContext.mapToPixel().mapUnitsPerPixel()
            self.targetSize.setWidth(
                rendererContext.extent().width() * sizeFact)
            self.targetSize.setHeight(
                rendererContext.extent().height() * sizeFact)
        debug(" targetSize: %d, %d" % (
            self.targetSize.width(), self.targetSize.height()), 3)

        # find matching OL resolution
        ext_width = rendererContext.extent().width()
        ext_height = rendererContext.extent().height()
        target_w = self.targetSize.width() or 1
        target_h = self.targetSize.height() or 1
        if not math.isfinite(ext_width) or not math.isfinite(ext_height) or ext_width <= 0 or ext_height <= 0:
            debug("Invalid extent: %f x %f" % (ext_width, ext_height), 3)
            self.emitErrorImage()
            return
        qgisRes = ext_width / target_w
        olRes = None
        valid_resolutions = [r for r in self.page.resolutions() if r and math.isfinite(r) and r > 0]
        # QGIS 해상도에 가장 가까운 타일 줌(로그 스케일) — 첫 번째 res만 고르면 오차가 커질 수 있음
        if valid_resolutions:
            olRes = min(
                valid_resolutions,
                key=lambda r: abs(math.log10(r + 1e-30) - math.log10(qgisRes + 1e-30)),
            )
        if olRes is None:
            if valid_resolutions:
                olRes = min(valid_resolutions)
            else:
                debug("No matching OL resolution found (QGIS resolution: %f)" %
                      qgisRes)
                self.emitErrorImage()
                return
        try:
            olZoomIdx = valid_resolutions.index(olRes)
        except Exception:
            olZoomIdx = 0

        # adjust OpenLayers viewport to match QGIS extent
        if olRes is None or olRes <= 0:
            debug("Invalid OL resolution: %s" % olRes, 3)
            self.emitErrorImage()
            return
        olWidth = ext_width / olRes
        olHeight = ext_height / olRes
        # Infinity/NaN/과대값 방지 - 최대 8192px로 제한
        max_dim = 8192
        if not math.isfinite(olWidth) or not math.isfinite(olHeight) or olWidth <= 0 or olHeight <= 0:
            olWidth = self.targetSize.width() or 512
            olHeight = self.targetSize.height() or 512
        elif olWidth > max_dim or olHeight > max_dim:
            scale = min(max_dim / olWidth, max_dim / olHeight)
            olWidth = olWidth * scale
            olHeight = olHeight * scale
        olWidth = int(olWidth)
        olHeight = int(olHeight)
        if olWidth <= 0 or olHeight <= 0:
            olWidth = max(512, self.targetSize.width() or 512)
            olHeight = max(512, self.targetSize.height() or 512)
            olWidth = int(olWidth)
            olHeight = int(olHeight)
        debug("    adjust viewport: %f -> %f: %d x %d" % (qgisRes,
                                                          olRes, olWidth,
                                                          olHeight), 3)
        olSize = QSize(olWidth, olHeight)
        self.page.setViewportSize(olSize)
        
        try:
            if self.page and hasattr(self.page, 'mainFrame') and self.page.mainFrame():
                self.page.mainFrame().evaluateJavaScript("map.updateSize();")
            else:
                debug("[GUI THREAD] Page object is no longer valid in setup_map", 3)
                self.emitErrorImage()
                return
        except RuntimeError as e:
            debug(f"[GUI THREAD] RuntimeError in setup_map: {e}", 3)
            self.emitErrorImage()
            return
        except Exception as e:
            debug(f"[GUI THREAD] Exception in setup_map: {e}", 3)
            self.emitErrorImage()
            return
            
        self.img = QImage(olSize, QIMAGE_ARGB32_PREMULT)

        self.page.extent = rendererContext.extent()
        self.setupStartedAt = time.time()
        c = self.page.extent.center()
        cx, cy = c.x(), c.y()
        debug(
            "map setCenter zoom=%d res=%s qgisRes=%f extent (%f, %f, %f, %f)" % (
                olZoomIdx, olRes, qgisRes,
                self.page.extent.xMinimum(), self.page.extent.yMinimum(),
                self.page.extent.xMaximum(), self.page.extent.yMaximum(),
            ),
            3,
        )

        try:
            if self.page and hasattr(self.page, 'mainFrame') and self.page.mainFrame():
                # zoomToExtent(..., true)는 OL이 "가까운 줌"으로 다시 맞춰 Python에서 고른
                # 해상도/뷰포트와 어긋나 벡터와 스케일이 안 맞는다. 계산한 줌 인덱스로 강제한다.
                self.page.mainFrame().evaluateJavaScript(
                    "(function(){var z=Math.max(0,Math.min(%d,map.getNumZoomLevels()-1));"
                    "map.setCenter(new OpenLayers.LonLat(%f,%f),z);})();"
                    % (olZoomIdx, cx, cy)
                )
                olextent = self.page.mainFrame().evaluateJavaScript("map.getExtent();")
                debug("map.getExtent result: {}".format(olextent), 1)
            else:
                debug("[GUI THREAD] Page object is no longer valid in setup_map (zoomToExtent)", 3)
                self.emitErrorImage()
                return
        except RuntimeError as e:
            debug(f"[GUI THREAD] RuntimeError in setup_map (zoomToExtent): {e}", 3)
            self.emitErrorImage()
            return
        except Exception as e:
            debug(f"[GUI THREAD] Exception in setup_map (zoomToExtent): {e}", 3)
            self.emitErrorImage()
            return
            
        debug("Resulting OL extent: %s" % olextent, 3)
        if olextent is None or not hasattr(olextent, '__getitem__'):
            debug("map.zoomToExtent failed")
            # map.setCenter and other operations throw "undefined[0]:
            # TypeError: 'null' is not an object" on first page load
            # We ignore that and render the initial map with wrong extents
            # self.emitErrorImage()
            # return
        else:
            reloffset = abs((self.page.extent.yMaximum()-olextent[
                "top"])/self.page.extent.xMinimum())
            debug("relative offset yMaximum %f" % reloffset, 3)
            # WebKit/WebEngine 모두 map.getExtent 기반 shift 체크는 오탐이 많아 렌더를 중단하지 않는다.
            # 실제 렌더 결과는 mapTimeout/renderMap 단계에서 판정한다.
            if reloffset > 0.1:
                debug("Extent shift detected but ignored: %s (backend=%s)" % (reloffset, WEB_BACKEND), 1)
        self.mapFinished = False
        self._olZoomIdxThisPass = olZoomIdx
        self.timer.start()
        self.timerMax.start()

    def checkMapUpdate(self):
        try:
            if self.page and hasattr(self.page, 'mainFrame') and self.page.mainFrame():
                if self.layerType.emitsLoadEnd:
                    # wait for OpenLayers to finish loading
                    loadEndOL = self.page.mainFrame().evaluateJavaScript("loadEnd")
                    debug("waiting for loadEnd: renderingStopped=%r loadEndOL=%r" % (
                          self.context.renderingStopped(), loadEndOL), 4)
                    if loadEndOL is not None:
                        self.mapFinished = loadEndOL
                    else:
                        debug("OpenlayersLayer Warning: Could not get loadEnd")

                # emitsLoadEnd가 False인 레이어(예: 카카오)는 기존 코드에서
                # 이 블록이 실행되지 않아 mapTimeout(수 초)까지 대기했다.
                if not self.mapFinished and hasattr(self, "setupStartedAt"):
                    elapsed = time.time() - self.setupStartedAt
                    partial_after = (
                        WEBENGINE_PARTIAL_RENDER_AFTER_SEC
                        if WEB_BACKEND == "webengine"
                        else LEGACY_PARTIAL_RENDER_AFTER_SEC
                    )
                    if elapsed >= partial_after:
                        debug(
                            "partial render after %.2fs (backend=%s, emitsLoadEnd=%s)"
                            % (partial_after, WEB_BACKEND, self.layerType.emitsLoadEnd),
                            1,
                        )
                        self.mapFinished = True

                if self.mapFinished:
                    self.timerMax.stop()
                    self.timer.stop()

                    self.renderMap()

                    self.finished.emit()
            else:
                debug("[GUI THREAD] Page object is no longer valid in checkMapUpdate", 3)
                self.emitErrorImage()
        except RuntimeError as e:
            debug(f"[GUI THREAD] RuntimeError in checkMapUpdate: {e}", 3)
            self.emitErrorImage()
        except Exception as e:
            debug(f"[GUI THREAD] Exception in checkMapUpdate: {e}", 3)
            self.emitErrorImage()

    def renderMap(self):
        debug("[GUI THREAD] renderMap begin", 1)
        rendererContext = self.context
        if rendererContext.painter().device().logicalDpiX() != int(self.outputDpi):
            printScale = 25.4 / self.outputDpi  # OL DPI to printer pixels
            rendererContext.painter().scale(printScale, printScale)

        # render OpenLayers to image
        painter = QPainter(self.img)
        try:
            if WEB_BACKEND == "webengine":
                # WebEngine는 프레임 렌더가 비동기이므로 캡처 전에 짧게 이벤트를 돌려준다.
                settle_loop = QEventLoop()
                QTimer.singleShot(WEBENGINE_SETTLE_BEFORE_CAPTURE_MS, settle_loop.quit)
                _event_loop_exec(settle_loop)
            if self.page and hasattr(self.page, 'mainFrame') and self.page.mainFrame():
                self.page.mainFrame().render(painter)
                debug("[GUI THREAD] frame rendered to image", 1)
            else:
                debug("[GUI THREAD] Page object is no longer valid in renderMap", 3)
                painter.end()
                self.emitErrorImage()
                return
        except RuntimeError as e:
            debug(f"[GUI THREAD] RuntimeError in renderMap: {e}", 3)
            painter.end()
            self.emitErrorImage()
            return
        except Exception as e:
            debug(f"[GUI THREAD] Exception in renderMap: {e}", 3)
            painter.end()
            self.emitErrorImage()
            return
        painter.end()
        # WebKit 시절에는 없던 처리. True면 흰 프레임 시 직전 성공 프레임 재사용(체감이 달라질 수 있음).
        if WEB_BACKEND == "webengine" and WEBENGINE_REUSE_LAST_GOOD_FRAME:
            if _is_mostly_white(self.img):
                prev = getattr(self.page, "lastGoodImage", None)
                prev_z = getattr(self.page, "lastGoodOlZoomIdx", None)
                this_z = getattr(self, "_olZoomIdxThisPass", None)
                same_zoom = prev_z is None or this_z is None or prev_z == this_z
                if (
                    prev is not None
                    and prev.size() == self.img.size()
                    and same_zoom
                ):
                    debug("[GUI THREAD] white frame detected, reusing last good frame", 1)
                    self.img = prev.copy()
            else:
                self.page.lastGoodImage = self.img.copy()
                self.page.lastGoodOlZoomIdx = getattr(self, "_olZoomIdxThisPass", None)
        try:
            debug("[GUI THREAD] image size after render: {}x{}".format(self.img.width(), self.img.height()), 1)
            # 실제 렌더 결과 확인을 위해 마지막 프레임을 파일로 저장
            if DEBUG_SAVE_RENDER_IMAGE:
                self.img.save(DEBUG_IMAGE_PATH, "PNG")
                debug("[GUI THREAD] render image saved: {}".format(DEBUG_IMAGE_PATH), 1)
        except Exception:
            pass

        if self.img.size() != self.targetSize:
            targetWidth = self.targetSize.width()
            targetHeight = self.targetSize.height()
            # scale using QImage for better quality
            debug("    scale image: %i x %i -> %i x %i" % (
                self.img.width(), self.img.height(),
                  targetWidth, targetHeight), 3)
            self.img = self.img.scaled(targetWidth, targetHeight,
                                       QT_KEEP_ASPECT_RATIO or Qt.KeepAspectRatio,
                                       QT_SMOOTH_TRANSFORMATION or Qt.SmoothTransformation)

        # save current state
        self.page.lastExtent = rendererContext.extent()
        self.page.lastViewPortSize = rendererContext.painter().viewport().size()
        self.page.lastLogicalDpi = rendererContext.painter().device().logicalDpiX()
        self.page.lastOutputDpi = self.outputDpi
        self.page.lastMapUnitsPerPixel = rendererContext.mapToPixel().mapUnitsPerPixel()

    def mapTimeout(self):
        debug("mapTimeout reached", 1)
        self.timer.stop()
        # if not self.layerType.emitsLoadEnd:
        self.renderMap()
        self.finished.emit()

    def emitErrorImage(self):
        debug("emitErrorImage called", 1)
        self.img = QImage()
        self.targetSize = self.img.size
        self.finished.emit()


class OpenlayersRenderer(QgsMapLayerRenderer):
    def __init__(self, layer, context, webPage, layerType):
        """ Initialize the object. This function is still run in the GUI thread.
            Should refrain from doing any heavy work.
        """
        QgsMapLayerRenderer.__init__(self, layer.id())
        self.context = context
        self.controller = OpenlayersController(None,
                                               context, webPage, layerType)
        self.loop = None

    def render(self):
        """ do the rendering. This function is called in the worker thread """

        debug("[WORKER THREAD] Calling request() asynchronously", 1)
        QMetaObject.invokeMethod(self.controller, "request")

        # setup a timer that checks whether the rendering has not been stopped
        # in the meanwhile
        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(self.onTimeout)
        timer.start()

        debug("[WORKER THREAD] Waiting for the async request to complete", 1)
        self.loop = QEventLoop()
        self.controller.finished.connect(self.loop.exit)
        _event_loop_exec(self.loop)

        debug("[WORKER THREAD] Async request finished", 1)

        painter = self.context.painter()
        painter.drawImage(0, 0, self.controller.img)
        return True

    def onTimeout(self):
        """ periodically check whether the rendering should not be stopped """
        if WEB_BACKEND == "webkit" and self.context.renderingStopped():
            debug("[WORKER THREAD] Cancelling rendering", 3)
            self.loop.exit()


class OpenlayersLayer(QgsPluginLayer):

    LAYER_TYPE = "openlayers"
    LAYER_PROPERTY = "ol_layer_type"
    MAX_ZOOM_LEVEL = 15
    SCALE_ON_MAX_ZOOM = 13540  # QGIS scale for 72 dpi

    def __init__(self, iface, olLayerTypeRegistry):
        QgsPluginLayer.__init__(self,
                                OpenlayersLayer.LAYER_TYPE,
                                "OpenLayers plugin layer")
        self.setValid(True)

        self.olLayerTypeRegistry = olLayerTypeRegistry
        self.layerType = None

        self.iface = iface
        self.olWebPage = OLWebPage(self)

    def readXml(self, node, context):
        # early read of custom properties
        self.readCustomProperties(node)

        # get layer type
        ol_layer_type = None
        ol_layer_type_name = self.customProperty(
            OpenlayersLayer.LAYER_PROPERTY, "")
        if ol_layer_type_name != "":
            ol_layer_type = self.olLayerTypeRegistry.getByName(
                ol_layer_type_name)
        else:
            # handle ol_layer_type idx stored in layer node
            # (OL plugin <= 1.1.2)
            ol_layer_type_idx = int(node.toElement().attribute(
                "ol_layer_type", "-1"))
            if ol_layer_type_idx != -1:
                ol_layer_type = self.olLayerTypeRegistry.getById(
                    ol_layer_type_idx)

        if ol_layer_type is not None:
            self.setLayerType(ol_layer_type)
        else:
            # Set default layer type (VWorld Street - 항상 등록됨)
            default_type = self.olLayerTypeRegistry.getByName("VWorld Street") or self.olLayerTypeRegistry.getByName("Kakao Street")
            if not default_type and self.olLayerTypeRegistry.types():
                default_type = list(self.olLayerTypeRegistry.types())[0]
            if default_type:
                self.setLayerType(default_type)
            msg = "Obsolete or unknown layer type '%s', using default" % ol_layer_type_name
            self.iface.messageBar().pushMessage("OpenLayers Plugin", msg,
                                                level=Qgis.MessageLevel(1))
            QgsMessageLog.logMessage(msg, "OpenLayers Plugin",
                                     QgsMessageLog.WARNING)

        return True

    def writeXml(self, node, doc, context):
        element = node.toElement()
        # write plugin layer type to project
        # (essential to be read from project)
        element.setAttribute("type", "plugin")
        element.setAttribute("name", OpenlayersLayer.LAYER_TYPE)
        return True

    def setLayerType(self, layerType):
        qDebug(" setLayerType: %s" % layerType.layerTypeName)
        self.layerType = layerType
        self.setCustomProperty(OpenlayersLayer.LAYER_PROPERTY,
                               layerType.layerTypeName)
        coordRefSys = self.layerType.coordRefSys(None)  # FIXME
        self.setCrs(coordRefSys)
        
        # set layer's full extent, 2014-06-12 minpa lee
        ext = self.layerType.fullExtent
        self.setExtent(QgsRectangle(ext[0], ext[1], ext[2], ext[3]))

    def createMapRenderer(self, context):
        return OpenlayersRenderer(self, context,
                                  self.olWebPage, self.layerType)
                                  
    def setTransformContext(self, transformContext):
        exta = 1
        
