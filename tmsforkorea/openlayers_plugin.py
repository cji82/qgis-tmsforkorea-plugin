# -*- coding: utf-8 -*-
"""
/***************************************************************************
OpenLayers Plugin
A QGIS plugin

                             -------------------
begin                : 2009-11-30
copyright            : (C) 2009 by Pirmin Kalberer, Sourcepole
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
# Import the PyQt and QGIS libraries
from qgis.PyQt.QtCore import (QSettings, QTranslator, QCoreApplication, qVersion, Qt, QTimer)
from qgis.PyQt.QtWidgets import (QApplication, QLineEdit, QInputDialog,
                                 QAction, QMenu)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (QgsCoordinateTransform, Qgis, QgsProject,
                       QgsPluginLayerRegistry, QgsLayerTree, QgsMapLayer, QgsLayerTreeLayer,
                       QgsRasterLayer, QgsMessageLog, QgsDataSourceUri)

from . import resources_rc
from .about_dialog import AboutDialog
from .weblayers.weblayer_registry import WebLayerTypeRegistry
from .weblayers.weblayer import WebLayer, WebLayer3857, WebLayer5179

# 설정 관리 기능 추가
from .weblayers.map_service_manager import MapServiceManager
from .weblayers.ui_service_manager_dialog import ServiceManagerDialog
from .weblayers.map_service_layers import create_map_service_layers

from .weblayers.daum_maps import (
    WebLayerDaum5181,
    OlDaumStreetLayer, OlDaumSatelliteLayer, OlDaumHybridLayer,
    OlDaumPhysicalLayer, OlDaumCadstralLayer
)
from .weblayers.naver_maps_old import (
    OlNaverStreet3857Layer, OlNaverSatellite3857Layer, OlNaverHybrid3857Layer,
    OlNaverPhysical3857Layer, OlNaverStreet5179Layer, OlNaverSatellite5179Layer,
    OlNaverHybrid5179Layer, OlNaverPhysical5179Layer, OlNaverCadastral5179Layer
)
from .weblayers.vworld_maps import (
    OlVWorldStreetLayer, OlVWorldSatelliteLayer, OlVWorldGrayLayer, OlVWorldHybridLayer
)

from .weblayers.ngii_maps import (OlNgiiStreetLayer,
                                  OlNgiiBlankLayer,
                                  OlNgiiEnglishLayer,
                                  OlNgiiHighDensityLayer,
                                  OlNgiiColorBlindLayer)

from .weblayers.mango_maps import (OlMangoBaseMapLayer,
                                   OlMangoBaseMapGrayLayer,
                                   OlMangoHiDPIMapLayer,
                                   OlMangoHiDPIMapGrayLayer)

import os.path
import time
import collections
import requests

try:
    from .openlayers_layer import OpenlayersLayer
    from .openlayers_plugin_layer_type import OpenlayersPluginLayerType
    OPENLAYERS_AVAILABLE = True
except Exception:
    OpenlayersLayer = None
    OpenlayersPluginLayerType = None
    OPENLAYERS_AVAILABLE = False

try:
    from .openlayers_overview import OLOverview
    OVERVIEW_AVAILABLE = True
except Exception:
    OLOverview = None
    OVERVIEW_AVAILABLE = False


class OpenlayersPlugin:

    def __init__(self, iface):
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # Keep a reference to all OL layers to avoid GC
        self._ol_layers = []
        # initialize locale
        locale = QSettings().value("locale/userLocale")[0:2]
        localePath = os.path.join(self.plugin_dir, "i18n", "openlayers_{}.qm".format(locale))

        if os.path.exists(localePath):
            self.translator = QTranslator()
            self.translator.load(localePath)

            if qVersion() > "4.3.3":
                QCoreApplication.installTranslator(self.translator)

        # 설정 관리자 초기화
        self.service_manager = MapServiceManager()
        self._olLayerTypeRegistry = WebLayerTypeRegistry(self)
        self.olOverview = OLOverview(iface, self._olLayerTypeRegistry) if OVERVIEW_AVAILABLE else None
        self.dlgAbout = AboutDialog()
        self.pluginLayerRegistry = QgsPluginLayerRegistry()
        self.openlayers_available = OPENLAYERS_AVAILABLE
        self.overview_available = OVERVIEW_AVAILABLE
        
        # 설정 관리 다이얼로그
        self.service_manager_dialog = None

    def initGui(self):
        self._olMenu = QMenu("TMS for Korea")
        self._olMenu.setIcon(QIcon(":/plugins/tmsforkorea/openlayers.png"))

        # Overview (QtWebKit 지원 환경에서만 활성화)
        if self.overview_available and self.olOverview is not None:
            self.overviewAddAction = QAction(QApplication.translate("OpenlayersPlugin", "OpenLayers Overview"), self.iface.mainWindow())
            self.overviewAddAction.setCheckable(True)
            self.overviewAddAction.setChecked(False)
            self.overviewAddAction.toggled.connect(self.olOverview.setVisible)
            self._olMenu.addAction(self.overviewAddAction)
        else:
            self.overviewAddAction = None

        self._actionAbout = QAction(QApplication.translate("dlgAbout", "About OpenLayers Plugin"), self.iface.mainWindow())
        self._actionAbout.triggered.connect(self.dlgAbout.show)
        self._olMenu.addAction(self._actionAbout)
        self.dlgAbout.finished.connect(self._publicationInfoClosed)

        # 설정 관리 액션 추가
        self._actionSettings = QAction(QApplication.translate("ServiceManagerDialog", "지도 서비스 설정"), self.iface.mainWindow())
        self._actionSettings.triggered.connect(self.show_settings_dialog)
        self._olMenu.addAction(self._actionSettings)

        self.register_layer_types()

        # NGII - 5179
        #self._olLayerTypeRegistry.register(OlNgiiStreetLayer())
        #self._olLayerTypeRegistry.register(OlNgiiBlankLayer())
        #self._olLayerTypeRegistry.register(OlNgiiEnglishLayer())
        #self._olLayerTypeRegistry.register(OlNgiiHighDensityLayer())
        #self._olLayerTypeRegistry.register(OlNgiiColorBlindLayer())

        # Mango - 3857
        #self._olLayerTypeRegistry.register(OlMangoBaseMapLayer())
        #self._olLayerTypeRegistry.register(OlMangoBaseMapGrayLayer())
        #self._olLayerTypeRegistry.register(OlMangoHiDPIMapLayer())
        #self._olLayerTypeRegistry.register(OlMangoHiDPIMapGrayLayer())

        for group in self._olLayerTypeRegistry.groups():
            groupMenu = group.menu()
            for layer in self._olLayerTypeRegistry.groupLayerTypes(group):
                layer.addMenuEntry(groupMenu, self.iface.mainWindow())
            self._olMenu.addMenu(groupMenu)

        # Create Web menu, if it doesn't exist yet
        self.iface.addPluginToWebMenu("_tmp", self._actionAbout)
        self._menu = self.iface.webMenu()
        self._menu.addMenu(self._olMenu)
        self.iface.removePluginWebMenu("_tmp", self._actionAbout)

        # Register plugin layer type
        if self.openlayers_available and OpenlayersPluginLayerType is not None:
            self.pluginLayerType = OpenlayersPluginLayerType(
                self.iface, self.setReferenceLayer, self._olLayerTypeRegistry)
            self.pluginLayerRegistry.addPluginLayerType(self.pluginLayerType)
        else:
            self.pluginLayerType = None

        QgsProject.instance().readProject.connect(self.projectLoaded)
        QgsProject.instance().projectSaved.connect(self.projectSaved)

    def unload(self):
        self.iface.webMenu().removeAction(self._olMenu.menuAction())

        if self.olOverview is not None:
            self.olOverview.setVisible(False)
            del self.olOverview

        # Unregister plugin layer type
        if self.pluginLayerType is not None and OpenlayersLayer is not None:
            self.pluginLayerRegistry.removePluginLayerType(
                OpenlayersLayer.LAYER_TYPE)

        QgsProject.instance().readProject.disconnect(self.projectLoaded)
        QgsProject.instance().projectSaved.disconnect(self.projectSaved)

    def show_settings_dialog(self):
        """설정 관리 다이얼로그 표시"""
        if self.service_manager_dialog is None:
            self.service_manager_dialog = ServiceManagerDialog(
                self.service_manager, self.iface.mainWindow(), self.iface
            )
            self.service_manager_dialog.configUpdated.connect(self.on_config_updated)
        
        self.service_manager_dialog.show()
        self.service_manager_dialog.raise_()
        self.service_manager_dialog.activateWindow()
    
    def on_config_updated(self):
        """설정 업데이트 시 호출"""
        QgsMessageLog.logMessage(
            "지도 서비스 설정이 업데이트되었습니다. 새로 추가된 레이어는 플러그인 재시작 후 표시됩니다.",
            "TMS for Korea"
        )

    def register_layer_types(self):
        """map_services.json 기반 OpenLayers 메뉴를 우선 등록하고, 실패 시 번들 정적 HTML로 폴백"""
        if not self.openlayers_available:
            self.register_xyz_layers_for_qgis4()
            return

        try:
            dynamic_layers = create_map_service_layers(self.service_manager)
            for layer in dynamic_layers:
                self._olLayerTypeRegistry.register(layer)
            QgsMessageLog.logMessage(
                QApplication.translate(
                    "OpenlayersPlugin",
                    "Registered {0} OpenLayers layer type(s) from map_services.json.",
                ).format(len(dynamic_layers)),
                "TMS for Korea",
            )
            return
        except Exception as e:
            QgsMessageLog.logMessage(
                QApplication.translate(
                    "OpenlayersPlugin",
                    "JSON-based OpenLayers layer registration failed; using bundled static HTML. {0}",
                ).format(str(e)),
                "TMS for Korea",
            )

        # 정적 HTML 폴백
        for layer_cls in [
            OlDaumStreetLayer, OlDaumSatelliteLayer, OlDaumHybridLayer,
            OlDaumPhysicalLayer, OlDaumCadstralLayer,
            OlNaverStreet3857Layer, OlNaverSatellite3857Layer,
            OlNaverHybrid3857Layer, OlNaverPhysical3857Layer,
            OlNaverStreet5179Layer, OlNaverSatellite5179Layer,
            OlNaverHybrid5179Layer, OlNaverPhysical5179Layer,
            OlNaverCadastral5179Layer,
            OlVWorldStreetLayer, OlVWorldSatelliteLayer,
            OlVWorldGrayLayer, OlVWorldHybridLayer
        ]:
            self._olLayerTypeRegistry.register(layer_cls())

    def _normalize_xyz_url(self, url):
        if not url:
            return url
        s = str(url).replace("${z}", "{z}").replace("${x}", "{x}").replace("${y}", "{y}")
        # 네이버 nrb: .png는 극소 빈 타일만 오는 경우가 많음 → QGIS XYZ는 .jpg 사용
        low = s.lower()
        if "map.pstatic.net/nrb/" in low and ".png" in s:
            if ".png?" in s:
                s = s.replace(".png?", ".jpg?", 1)
            elif s.lower().endswith(".png"):
                s = s[:-4] + ".jpg"
        return s

    def _xyz_raster_uri(self, tile_url, z_min=0, z_max=21, tile_pixel_ratio=1):
        """QGIS XYZ(WMS provider)용 URI. url 내 ?mt= 등이 있을 때 수동 '&' 연결보다 안전하게 인코딩."""
        ds = QgsDataSourceUri()
        ds.setParam("type", "xyz")
        ds.setParam("url", tile_url)
        ds.setParam("zmin", str(z_min))
        ds.setParam("zmax", str(z_max))
        if tile_pixel_ratio and int(tile_pixel_ratio) > 0:
            ds.setParam("tilePixelRatio", str(int(tile_pixel_ratio)))
        low = (tile_url or "").lower()
        if "map.pstatic.net/nrb/" in low:
            ds.setParam("http-header:referer", "https://map.naver.com/")
        return ds.uri(False)

    def _register_xyz_layer(self, layer):
        self._olLayerTypeRegistry.register(layer)

    def register_xyz_layers_for_qgis4(self):
        """map_services.json 기반 XYZ 레이어 등록(QGIS4 권장). 등록 개수 반환."""
        QgsMessageLog.logMessage(
            "map_services.json XYZ 레이어 모드로 등록합니다.",
            "TMS for Korea"
        )
        count = 0

        # Kakao (EPSG:5181, HTML 경로와 동일한 CRS 정의)
        for layer_type, name in [
            ("street", "Kakao Street"),
            ("satellite", "Kakao Satellite"),
            ("hybrid", "Kakao Hybrid"),
            ("physical", "Kakao Physical"),
            ("cadastral", "Kakao Cadastral"),
        ]:
            urls = [self._normalize_xyz_url(u) for u in self.service_manager.get_urls("daum_maps", layer_type, for_tile_fetch=True)]
            if not urls:
                continue
            layer = WebLayerDaum5181("Kakao Maps", "daum_icon.png", name, "dummy.html", xyzUrl=urls[0])
            layer.epsgList = [5181]
            layer.fullExtent = [-30000, -60000, 494288, 988576]
            self._register_xyz_layer(layer)
            count += 1

        # Naver 3857
        for layer_type, name in [
            ("street", "Naver Street"),
            ("satellite", "Naver Satellite"),
            ("hybrid", "Naver Hybrid"),
            ("physical", "Naver Physical"),
            ("cadastral", "Naver Cadastral"),
        ]:
            urls = [self._normalize_xyz_url(u) for u in self.service_manager.get_urls("naver_maps", layer_type, for_tile_fetch=True)]
            if not urls:
                continue
            layer = WebLayer3857("Naver Maps", "naver_icon.png", name, "dummy.html", xyzUrl=urls[0], tilePixelRatio=1)
            self._register_xyz_layer(layer)
            count += 1

        # VWorld 3857
        for layer_type, name in [
            ("street", "VWorld Street"),
            ("satellite", "VWorld Satellite"),
            ("gray", "VWorld 백지도"),
            ("hybrid", "VWorld Hybrid"),
        ]:
            urls = [self._normalize_xyz_url(u) for u in self.service_manager.get_urls("vworld_maps", layer_type, for_tile_fetch=True)]
            if not urls:
                continue
            xyz = urls if layer_type == "hybrid" and len(urls) > 1 else urls[0]
            layer = WebLayer3857("VWorld Maps", "vworld_icon.png", name, "dummy.html", xyzUrl=xyz, tilePixelRatio=1)
            self._register_xyz_layer(layer)
            count += 1

        return count

    def run(self):
        # Run method that performs all the real work
        pass

    def _focus_qgis_main_window(self):
        """연결 브라우저 갱신·레이어 추가 등으로 포커스가 빠진 뒤 메인 창으로 복구."""
        try:
            mw = self.iface.mainWindow()
            if mw is not None:
                mw.raise_()
                mw.activateWindow()
            self.iface.mapCanvas().setFocus()
        except Exception:
            pass

    def addLayer(self, layerType):
        try:
            if layerType.hasXYZUrl():
                # create XYZ layer
                self.createXYZLayer(layerType, layerType.displayName)
            else:
                if OpenlayersLayer is None:
                    QgsMessageLog.logMessage(
                        "QtWebKit이 없어 OpenLayers(HTML) 레이어는 사용할 수 없습니다. XYZ 레이어를 사용하세요.",
                        "TMS for Korea"
                    )
                    return
                # create OpenlayersLayer
                layer = OpenlayersLayer(self.iface, self._olLayerTypeRegistry)
                layer.setName(layerType.displayName)
                layer.setLayerType(layerType)

                if layer.isValid():
                    coordRefSys = layerType.coordRefSys(self.canvasCrs())
                    self.setMapCrs(coordRefSys)
                    QgsProject.instance().addMapLayer(layer)

                    self._ol_layers += [layer]

                    # last added layer is new reference
                    self.setReferenceLayer(layer)
        finally:
            # reloadConnections 등으로 작업 표시줄로 포커스가 빠지는 경우
            QTimer.singleShot(50, self._focus_qgis_main_window)

    def setReferenceLayer(self, layer):
        self.layer = layer

    def removeLayer(self, layerId):
        if self.layer is not None:
            if self.layer.id() == layerId:
                self.layer = None
            # TODO: switch to next available OpenLayers layer?

    def canvasCrs(self):
        mapCanvas = self.iface.mapCanvas()
        crs = mapCanvas.mapSettings().destinationCrs()
        return crs

    def setMapCrs(self, targetCRS):
        mapCanvas = self.iface.mapCanvas()
        mapExtent = mapCanvas.extent()

        sourceCRS = self.canvasCrs()
        QgsProject.instance().setCrs(targetCRS)
        mapCanvas.freeze(False)
        try:
            coordTrans = QgsCoordinateTransform(sourceCRS, targetCRS, QgsProject.instance())
            mapExtent = coordTrans.transform(mapExtent, QgsCoordinateTransform.ForwardTransform)
            mapCanvas.setExtent(mapExtent)
        except:
            pass

    def projectLoaded(self):
        # replace old OpenlayersLayer with XYZ layer(OL plugin <= 1.3.6)
        if OpenlayersLayer is None:
            return
        rootGroup = self.iface.layerTreeView().layerTreeModel().rootGroup()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayer.PluginLayer and layer.pluginLayerType() == OpenlayersLayer.LAYER_TYPE:
                if layer.layerType.hasXYZUrl():
                    # replace layer
                    xyzLayer, url = self.createXYZLayer(layer.layerType,
                                                        layer.name())
                    if xyzLayer.isValid():
                        self.replaceLayer(rootGroup, layer, xyzLayer)

    def _hasOlLayer(self):
        if OpenlayersLayer is None:
            return False
        for layer in QgsProject.instance().mapLayers().values():
            if layer.customProperty("ol_layer_type"):
                return True
        return False

    def _publicationInfo(self):
        cloud_info_off = QSettings().value("Plugin-OpenLayers/cloud_info_off",
                                           defaultValue=False, type=bool)
        day = 3600*24
        now = time.time()
        lastInfo = QSettings().value("Plugin-OpenLayers/cloud_info_ts",
                                     defaultValue=0.0, type=float)
        if lastInfo == 0.0:
            lastInfo = now-20*day  # Show first time after 10 days
            QSettings().setValue("Plugin-OpenLayers/cloud_info_ts", lastInfo)
        days = (now-lastInfo)/day
        if days >= 30 and not cloud_info_off:
            self.dlgAbout.tabWidget.setCurrentWidget(
                self.dlgAbout.tab_publishing)
            self.dlgAbout.show()
            QSettings().setValue("Plugin-OpenLayers/cloud_info_ts", now)

    def _publicationInfoClosed(self):
        QSettings().setValue("Plugin-OpenLayers/cloud_info_off",
                             self.dlgAbout.cb_publishing.isChecked())

    def projectSaved(self):
        if self._hasOlLayer():
            self._publicationInfo()

    def createXYZLayer(self, layerType, name):
        # create XYZ layer with tms url as uri
        provider = "wms"

        # isinstance(P, (list, tuple, np.ndarray))
        xyzUrls = layerType.xyzUrlConfig()
        if isinstance(xyzUrls, (list, tuple)):
            xyzUrls = [self._normalize_xyz_url(u) for u in xyzUrls]
        else:
            xyzUrls = self._normalize_xyz_url(xyzUrls)
        layerName = name
        tilePixelRatio = layerType.tilePixelRatio

        coordRefSys = layerType.coordRefSys(self.canvasCrs())
        self.setMapCrs(coordRefSys)

        if isinstance(xyzUrls, (list)):
            # create group layer
            root = QgsProject.instance().layerTreeRoot()
            layer = root.addGroup(layerType.groupName)

            i = 0
            for xyzUrl in xyzUrls:
                tmsLayerName = layerName;

                # QgsDataSourceUri: url 안의 ?mt=… 가 상위 '&'로 잘못 쪼개지지 않도록 처리
                z_max = 21 if "map.pstatic.net/nrb/" in (xyzUrl or "").lower() else 18
                uri = self._xyz_raster_uri(
                    xyzUrl,
                    z_max=z_max,
                    tile_pixel_ratio=tilePixelRatio if tilePixelRatio > 0 else 0,
                )

                if i > 0:
                    tmsLayerName = layerName + " Label"

                tmsLayer = QgsRasterLayer(uri, tmsLayerName, provider, QgsRasterLayer.LayerOptions())
                tmsLayer.setCustomProperty("ol_layer_type", tmsLayerName)

                layer.insertChildNode(0, QgsLayerTreeLayer(tmsLayer))
                i = i + 1

                if tmsLayer.isValid():
                    QgsProject.instance().addMapLayer(tmsLayer, False)
                    self._ol_layers += [tmsLayer]

                    # last added layer is new reference
                    self.setReferenceLayer(tmsLayer)
                    # add to XYT Tiles
                    self.addToXYZTiles(tmsLayerName, xyzUrl, tilePixelRatio)
        else:
            z_max = 21 if "map.pstatic.net/nrb/" in (xyzUrls or "").lower() else 18
            uri = self._xyz_raster_uri(
                xyzUrls,
                z_max=z_max,
                tile_pixel_ratio=tilePixelRatio if tilePixelRatio > 0 else 0,
            )

            layer = QgsRasterLayer(uri, layerName, provider, QgsRasterLayer.LayerOptions())
            layer.setCustomProperty("ol_layer_type", layerName)

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self._ol_layers += [layer]

                # last added layer is new reference
                self.setReferenceLayer(layer)
                # add to XYT Tiles
                self.addToXYZTiles(layerName, xyzUrls, tilePixelRatio)

        # reload connections to update Browser Panel content
        self.iface.reloadConnections()

        return layer, xyzUrls

    def addToXYZTiles(self, name, url, tilePixelRatio):
        # store xyz config into qgis settings
        settings = QSettings()
        settings.beginGroup("qgis/connections-xyz")
        settings.setValue("%s/authcfg" % (name), "")
        settings.setValue("%s/password" % (name), "")
        low = (url or "").lower()
        settings.setValue("%s/referer" % (name), "https://map.naver.com/" if "map.pstatic.net/nrb/" in low else "")
        settings.setValue("%s/url" % (name), url)
        settings.setValue("%s/username" % (name), "")
        # specify max/min or else only a picture of the map is saved in settings
        settings.setValue("%s/zmax" % (name), "21" if "map.pstatic.net/nrb/" in low else "18")
        settings.setValue("%s/zmin" % (name), "0")
        if tilePixelRatio >= 0 and tilePixelRatio <= 2:
            settings.setValue("%s/tilePixelRatio" % (name), str(tilePixelRatio))
        settings.endGroup()

    def replaceLayer(self, group, oldLayer, newLayer):
        index = 0
        for child in group.children():
            if QgsLayerTree.isLayer(child):
                if child.layerId() == oldLayer.id():
                    # insert new layer
                    QgsProject.instance().addMapLayer(newLayer, False)
                    newLayerNode = group.insertLayer(index, newLayer)
                    newLayerNode.setVisible(child.isVisible())

                    # remove old layer
                    QgsProject.instance().removeMapLayer(
                        oldLayer.id())

                    msg = "Updated layer '%s' from old OpenLayers Plugin version" % newLayer.name()
                    self.iface.messageBar().pushMessage(
                        "OpenLayers Plugin", msg, level=Qgis.MessageLevel(0))
                    QgsMessageLog.logMessage(
                        msg, "OpenLayers Plugin", QgsMessageLog.INFO)

                    # layer replaced
                    return True
            else:
                if self.replaceLayer(child, oldLayer, newLayer):
                    # layer replaced in child group
                    return True

            index += 1

        # layer not in this group
        return False
