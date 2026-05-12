# -*- coding: utf-8 -*-
"""
map_services.json 기반 OpenLayers 웹 레이어
- HTML 생성 시점에 manager가 들고 있는 URL(설정·저장된 JSON)을 박아 넣음
- 실행 중 타일 요청마다 URL을 다시 조회하지는 않음. 설정 변경 후에는 플러그인 재시작 또는 레이어 다시 로드 시 반영
"""

import os
from qgis.core import QgsCoordinateReferenceSystem, Qgis
from .weblayer import WebLayer


class MapServiceWebLayer(WebLayer):
    """
    map_services.json(및 manager 메모리)의 URL로 OpenLayers용 HTML을 생성하는 레이어.
    정적 Ol* 레이어와 달리 번들 HTML/JS에 고정 URL을 두지 않고 JSON 기준으로 만든다.
    """

    emitsLoadEnd = True

    def __init__(self, service_manager, service_name, layer_type,
                 group_name, group_icon, display_name,
                 epsg, max_extent, map_center, js_generator_name):
        """
        js_generator_name: 'daum', 'naver' 등 - map_service_manager의 생성기 메서드명
        """
        self.service_manager = service_manager
        self.service_name = service_name
        self.layer_type = layer_type
        self.js_generator_name = js_generator_name
        self.epsg = epsg
        self.max_extent = max_extent
        self.map_center = map_center

        temp_filename = f"mapservice_{service_name}_{layer_type}.html"
        super().__init__(groupName=group_name, groupIcon=group_icon,
                         name=display_name, html=temp_filename)
        if epsg == 5179:
            self.fullExtent = [90112, 1192896, 1990673, 2761664]
            self.epsgList = [5179]
        elif epsg == 3857:
            self.fullExtent = [-20037508.34, -20037508.34, 20037508.34, 20037508.34]
            self.epsgList = [3857]
        else:
            self.fullExtent = [-30000, -60000, 494288, 988576]
            self.epsgList = [5181]
        self.MAX_ZOOM_LEVEL = 14
        self.SCALE_ON_MAX_ZOOM = 13540

    def html_url(self):
        """map_services.json에서 URL을 읽어 동적 HTML 생성 후 반환"""
        html_content = self._generate_html_content()
        html_dir = os.path.join(os.path.dirname(__file__), "html")
        temp_dir = os.path.join(html_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, self._html)
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception:
            pass
        url = "file:///%s" % temp_path.replace("\\", "/")
        return url

    def _generate_html_content(self):
        """map_services.json 기반 HTML 생성"""
        extra_scripts = ""
        if self.js_generator_name == 'daum':
            js_code = self.service_manager.generate_daum_js_layer_code(
                self.layer_type, f"Daum{self.layer_type.capitalize()}")
            projection = "EPSG:5181"
            max_extent = "-30000, -60000, 494288, 988576"
            map_center = "200000, 500000"
            spherical_mercator = "false"
            max_res = "2048"
            num_zoom = "14"
        elif self.js_generator_name == 'naver_3857':
            js_code = self.service_manager.generate_naver_3857_js_layer_code(
                self.layer_type, f"Naver3857{self.layer_type.capitalize()}")
            projection = "EPSG:3857"
            max_extent = "-20037508.34, -20037508.34, 20037508.34, 20037508.34"
            map_center = "14243426, 4302306"
            spherical_mercator = "true"
            max_res = "156543.0339"
            num_zoom = "19"
        elif self.js_generator_name == 'naver_5179':
            extra_scripts = '<script src="../proj4.js"></script>\n<script src="../proj4_5179.js"></script>\n<script src="../naver_5179_tile.js"></script>\n'
            js_code = self.service_manager.generate_naver_5179_js_layer_code(
                self.layer_type, f"Naver5179{self.layer_type.capitalize()}")
            projection = "EPSG:5179"
            max_extent = "90112, 1192896, 1990673, 2761664"
            map_center = "200000, 500000"
            spherical_mercator = "false"
            max_res = "2048"
            num_zoom = "14"
        elif self.js_generator_name == 'vworld':
            js_code = self.service_manager.generate_vworld_js_layer_code(
                self.layer_type, f"VWorld{self.layer_type.capitalize()}")
            projection = "EPSG:3857"
            max_extent = "-20037508.34, -20037508.34, 20037508.34, 20037508.34"
            map_center = "14243426, 4302306"
            spherical_mercator = "true"
            max_res = "156543.0339"
            num_zoom = "19"
        elif self.js_generator_name == 'vworld_hybrid':
            # Hybrid: 위성+하이브리드 2레이어 (별도 init 코드)
            js_code = ""
            hybrid_init = self.service_manager.generate_vworld_hybrid_init_js()
            projection = "EPSG:3857"
            max_extent = "-20037508.34, -20037508.34, 20037508.34, 20037508.34"
            map_center = "14243426, 4302306"
            spherical_mercator = "true"
            max_res = "156543.0339"
            num_zoom = "19"
        else:
            return ""

        layer_class_map = {
            'daum': f"Daum{self.layer_type.capitalize()}",
            'naver_3857': f"Naver3857{self.layer_type.capitalize()}",
            'naver_5179': f"Naver5179{self.layer_type.capitalize()}",
            'vworld': f"VWorld{self.layer_type.capitalize()}",
            'vworld_hybrid': 'VWorldHybrid',
        }
        layer_class = layer_class_map.get(self.js_generator_name, "Unknown")
        layer_var = layer_class[0].lower() + layer_class[1:].replace(' ', '')

        if self.js_generator_name == 'vworld_hybrid':
            add_layer_code = hybrid_init
        else:
            add_layer_code = f"""    var {layer_var} = new OpenLayers.Layer.{layer_class}("{self.displayName}",
        {{ sphericalMercator: {spherical_mercator}, eventListeners: {{ "loadstart": layerLoadStart, "loadend": layerLoadEnd }} }});
    map.addLayer({layer_var});"""

        return f'''<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>OpenLayers {self.displayName} Layer</title>
<link rel="stylesheet" href="../qgis.css" type="text/css">
<style type="text/css">
html, body, #map {{
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    overflow: hidden;
}}
</style>
<script src="../OpenLayers.js"></script>
{extra_scripts}
<script type="text/javascript">
{js_code}
</script>
<script src="../OlOverviewMarker.js"></script>
<script type="text/javascript">
var map;
var loadEnd;
var oloMarker;
function init() {{
    map = new OpenLayers.Map('map', {{
        theme: null,
        controls: [
            new OpenLayers.Control.Attribution(),
            new OpenLayers.Control.Navigation({{ dragPanOptions: {{ enableKinetic: true }} }})
        ],
        sphericalMercator: {spherical_mercator},
        projection: new OpenLayers.Projection("{projection}"),
        units: "m",
        maxResolution: {max_res},
        numZoomLevels: {num_zoom},
        maxExtent: new OpenLayers.Bounds({max_extent})
    }});
    loadEnd = false;
    function layerLoadStart(event) {{ loadEnd = false; }}
    function layerLoadEnd(event) {{ loadEnd = true; }}
{add_layer_code}
    map.setCenter(new OpenLayers.LonLat({map_center}), { '10' if spherical_mercator == 'true' else '1' });
    oloMarker = new OlOverviewMarker(map, getPathUpper(document.URL) + '/x.png');
}}
</script>
</head>
<body onload="init()">
<div id="map"></div>
</body>
</html>'''

    def coordRefSys(self, mapCoordSys):
        coordRefSys = QgsCoordinateReferenceSystem()
        if Qgis.QGIS_VERSION_INT >= 10900:
            createCrs = coordRefSys.createFromOgcWmsCrs("EPSG:%d" % self.epsg)
        else:
            createCrs = coordRefSys.createFromEpsg(self.epsg)
        if not createCrs and self.epsg == 5179:
            proj_def = "+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 "
            proj_def += "+towgs84=0,0,0,0,0,0,0 +units=m +no_defs"
            coordRefSys.createFromProj4(proj_def)
        elif not createCrs and self.epsg == 3857:
            proj_def = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs"
            coordRefSys.createFromProj4(proj_def)
        elif not createCrs and self.epsg == 5181:
            proj_def = "+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=500000 +ellps=GRS80 "
            proj_def += "+towgs84=0,0,0,0,0,0,0 +units=m +no_defs"
            coordRefSys.createFromProj4(proj_def)
        return coordRefSys


def create_map_service_layers(service_manager):
    """map_services.json 기반 카카오/네이버/VWorld 레이어 생성 (전부 동적 로드)"""
    layers = []

    # Kakao Maps - EPSG:5181
    if service_manager.has_service('daum_maps'):
        for layer_type in ['street', 'satellite', 'hybrid', 'physical', 'cadastral']:
            if layer_type in service_manager.get_service_layers('daum_maps'):
                name_map = {
                    'street': 'Kakao Street',
                    'satellite': 'Kakao Satellite',
                    'hybrid': 'Kakao Hybrid',
                    'physical': 'Kakao Physical',
                    'cadastral': 'Kakao Cadastral'
                }
                layers.append(MapServiceWebLayer(
                    service_manager, 'daum_maps', layer_type,
                    'Kakao Maps', 'daum_icon.png', name_map[layer_type],
                    epsg=5181, max_extent=None, map_center=None,
                    js_generator_name='daum'
                ))

    # Naver Maps - 3857 (nrb 타일, Web Mercator)
    if service_manager.has_service('naver_maps'):
        for layer_type in ['street', 'satellite', 'hybrid', 'physical', 'cadastral']:
            if layer_type in service_manager.get_service_layers('naver_maps'):
                name_map = {
                    'street': 'Naver Street',
                    'satellite': 'Naver Satellite',
                    'hybrid': 'Naver Hybrid',
                    'physical': 'Naver Physical',
                    'cadastral': 'Naver Cadastral'
                }
                layers.append(MapServiceWebLayer(
                    service_manager, 'naver_maps', layer_type,
                    'Naver Maps', 'naver_icon.png', name_map[layer_type],
                    epsg=3857, max_extent=None, map_center=None,
                    js_generator_name='naver_3857'
                ))

        # Naver Maps - 5179 (proj4 좌표 변환)
        for layer_type in ['street', 'satellite', 'hybrid', 'physical', 'cadastral']:
            if layer_type in service_manager.get_service_layers('naver_maps'):
                name_map = {
                    'street': 'Naver Street - 5179',
                    'satellite': 'Naver Satellite - 5179',
                    'hybrid': 'Naver Hybrid - 5179',
                    'physical': 'Naver Physical - 5179',
                    'cadastral': 'Naver Cadastral - 5179'
                }
                layers.append(MapServiceWebLayer(
                    service_manager, 'naver_maps', layer_type,
                    'Naver Maps - 5179', 'naver_icon.png', name_map[layer_type],
                    epsg=5179, max_extent=None, map_center=None,
                    js_generator_name='naver_5179'
                ))

    # VWorld Maps - EPSG:3857
    if service_manager.has_service('vworld_maps'):
        for layer_type in ['street', 'satellite', 'gray']:
            if layer_type in service_manager.get_service_layers('vworld_maps'):
                name_map = {'street': 'VWorld Street', 'satellite': 'VWorld Satellite', 'gray': 'VWorld 백지도'}
                layers.append(MapServiceWebLayer(
                    service_manager, 'vworld_maps', layer_type,
                    'VWorld Maps', 'vworld_icon.png', name_map[layer_type],
                    epsg=3857, max_extent=None, map_center=None,
                    js_generator_name='vworld'
                ))
        if 'hybrid' in service_manager.get_service_layers('vworld_maps'):
            layers.append(MapServiceWebLayer(
                service_manager, 'vworld_maps', 'hybrid',
                'VWorld Maps', 'vworld_icon.png', 'VWorld Hybrid',
                epsg=3857, max_extent=None, map_center=None,
                js_generator_name='vworld_hybrid'
            ))

    return layers
