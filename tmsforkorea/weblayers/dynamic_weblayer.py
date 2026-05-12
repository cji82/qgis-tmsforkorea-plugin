# -*- coding: utf-8 -*-
"""
/***************************************************************************
Dynamic Web Layer
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

import os
import tempfile
from qgis.PyQt.QtCore import QUrl
from .weblayer import WebLayer
from .map_service_manager import MapServiceManager
from qgis.core import QgsCoordinateReferenceSystem, Qgis


class DynamicWebLayer(WebLayer):
    """
    설정 파일에서 동적으로 HTML을 생성하는 웹 레이어 클래스
    """
    
    def __init__(self, service_manager, service_name, layer_type, group_name, group_icon, display_name):
        self.service_manager = service_manager
        self.service_name = service_name
        self.layer_type = layer_type
        
        # 동적으로 HTML 생성
        html_content = self._generate_html_content()
        
        # 임시 HTML 파일 생성
        temp_html_file = self._create_temp_html_file(html_content)
        
        super().__init__(groupName=group_name, groupIcon=group_icon,
                        name=display_name, html=temp_html_file)
    
    def _generate_html_content(self):
        """설정 파일에서 HTML 내용 동적 생성"""
        config = self.service_manager.get_service_config(self.service_name, self.layer_type)
        urls = config.get('urls', [])
        attribution = config.get('attribution', '')
        
        # JavaScript 레이어 코드 생성
        layer_class_name = f"{self.service_name.capitalize()}{self.layer_type.capitalize()}"
        js_layer_code = self.service_manager.generate_js_layer_code(
            self.service_name, self.layer_type, layer_class_name
        )
        
        # HTML 템플릿 생성
        html_content = f"""
        <html xmlns="http://www.w3.org/1999/xhtml">
          <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
            <title>OpenLayers {layer_class_name} Layer</title>
            <link rel="stylesheet" href="qgis.css" type="text/css">
            <script src="OpenLayers.js"></script>
            <script type="text/javascript">
                {js_layer_code}
            </script>
            <script src="OlOverviewMarker.js"></script>
            <script type="text/javascript">
                var map;
                var loadEnd;
                var oloMarker; // OpenLayer Overview Marker
                function init() {{            
                    map = new OpenLayers.Map('map', {{
                      theme: null,
                      controls: [
                        new OpenLayers.Control.Attribution(),
                        new OpenLayers.Control.Navigation({{
                          dragPanOptions: {{
                            enableKinetic: true
                          }}
                        }})
                      ],
                      projection: new OpenLayers.Projection("EPSG:5181"),
                      units: "m",
                      maxResolution: 2048,
                      numZoomLevels: 14,
                      maxExtent: new OpenLayers.Bounds(-30000, -60000, 494288, 988576)
                    }});

                    loadEnd = false;
                    function layerLoadStart(event)
                    {{
                      loadEnd = false;
                    }}
                    
                    function layerLoadEnd(event)
                    {{
                      loadEnd = true;
                    }}
                    
                    var {layer_class_name.lower()} = new OpenLayers.Layer.{layer_class_name}("{display_name}",
                      {{
                        sphericalMercator: false,
                        eventListeners: {{
                          "loadstart": layerLoadStart,
                          "loadend": layerLoadEnd
                        }}
                      }}
                    );
                    
                    map.addLayer({layer_class_name.lower()});
                    map.setCenter(new OpenLayers.LonLat(200000 ,500000), 0); // Zoom level
                    
                    oloMarker = new OlOverviewMarker(map, getPathUpper(document.URL) + '/x.png');
                }}
            </script>
          </head>
          <body onload="init()">
            <div id="map"></div>
          </body>
        </html>
        """
        
        return html_content
    
    def _create_temp_html_file(self, html_content):
        """임시 HTML 파일 생성"""
        try:
            # 임시 디렉토리에 HTML 파일 생성
            temp_dir = os.path.join(os.path.dirname(__file__), "html", "temp")
            os.makedirs(temp_dir, exist_ok=True)
            
            filename = f"{self.service_name}_{self.layer_type}.html"
            temp_file_path = os.path.join(temp_dir, filename)
            
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return filename
            
        except Exception as e:
            # 에러 발생 시 기본 HTML 파일 사용
            return f"{self.service_name}_{self.layer_type}.html"
    
    def update_from_config(self):
        """설정 파일에서 업데이트"""
        # 새로운 HTML 내용 생성
        html_content = self._generate_html_content()
        
        # 임시 파일 업데이트
        temp_dir = os.path.join(os.path.dirname(__file__), "html", "temp")
        filename = f"{self.service_name}_{self.layer_type}.html"
        temp_file_path = os.path.join(temp_dir, filename)
        
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as e:
            pass


class DynamicWebLayerFactory:
    """
    동적 웹 레이어를 생성하는 팩토리 클래스
    """
    
    def __init__(self, service_manager):
        self.service_manager = service_manager
    
    def create_layer(self, service_name, layer_type, group_name, group_icon, display_name):
        """동적 웹 레이어 생성"""
        return DynamicWebLayer(
            self.service_manager, service_name, layer_type,
            group_name, group_icon, display_name
        )
    
    def create_all_layers(self):
        """모든 서비스의 모든 레이어 생성"""
        layers = []
        
        for service_name in self.service_manager.get_map_service_names():
            for layer_type in self.service_manager.get_service_layers(service_name):
                # 그룹 정보 설정
                if service_name == "daum_maps":
                    group_name = "Kakao Maps"
                    group_icon = "daum_icon.png"
                elif service_name == "naver_maps":
                    group_name = "Naver Maps"
                    group_icon = "naver_icon.png"
                elif service_name == "vworld_maps":
                    group_name = "VWorld Maps"
                    group_icon = "vworld_icon.png"
                else:
                    group_name = f"{service_name.capitalize()} Maps"
                    group_icon = "default_icon.png"
                
                # 표시 이름 설정
                display_name = f"{service_name.capitalize()} {layer_type.capitalize()}"
                
                # 레이어 생성
                layer = self.create_layer(
                    service_name, layer_type, group_name, group_icon, display_name
                )
                layers.append(layer)
        
        return layers


class ConfigurableWebLayer(WebLayer):
    """
    설정 파일 기반의 웹 레이어 클래스
    """
    
    def __init__(self, service_manager, service_name, layer_type, group_name, group_icon, display_name):
        self.service_manager = service_manager
        self.service_name = service_name
        self.layer_type = layer_type
        
        # 설정 파일에서 정보 가져오기
        config = self.service_manager.get_service_config(service_name, layer_type)
        urls = config.get('urls', [])
        attribution = config.get('attribution', '')
        
        # HTML 파일명 생성
        html_filename = f"{service_name}_{layer_type}.html"
        
        super().__init__(groupName=group_name, groupIcon=group_icon,
                        name=display_name, html=html_filename)
        
        # URL 정보 저장
        self._urls = urls
        self._attribution = attribution
    
    def get_urls(self):
        """URL 목록 반환"""
        return self._urls
    
    def get_attribution(self):
        """Attribution 반환"""
        return self._attribution
    
    def update_config(self):
        """설정 파일에서 업데이트"""
        config = self.service_manager.get_service_config(self.service_name, self.layer_type)
        self._urls = config.get('urls', [])
        self._attribution = config.get('attribution', '')
    
    def coordRefSys(self, mapCoordSys):
        """좌표계 설정"""
        # 네이버 지도의 경우 EPSG:5179 사용
        if self.service_name == 'naver_maps':
            epsg = 5179
        else:
            epsg = 3857  # 기본값
        
        coordRefSys = QgsCoordinateReferenceSystem()
        if Qgis.QGIS_VERSION_INT >= 10900:
            idEpsgRSGoogle = "EPSG:%d" % epsg
            createCrs = coordRefSys.createFromOgcWmsCrs(idEpsgRSGoogle)
        else:
            idEpsgRSGoogle = epsg
            createCrs = coordRefSys.createFromEpsg(idEpsgRSGoogle)
        
        if not createCrs:
            # EPSG:5179의 경우 수동으로 정의
            if epsg == 5179:
                proj_def = "+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 "
                proj_def += "+towgs84=0,0,0,0,0,0,0 +units=m +no_defs"
                isOk = coordRefSys.createFromProj4(proj_def)
                if not isOk:
                    return None
            else:
                return None
        
        return coordRefSys 