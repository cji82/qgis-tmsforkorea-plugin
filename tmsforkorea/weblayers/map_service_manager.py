#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
/***************************************************************************
Map Service Manager
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

import json
import os
import urllib.parse

# QGIS 환경인지 확인하고 조건부로 import
try:
    from qgis.PyQt.QtCore import QObject, pyqtSignal
    from qgis.core import QgsMessageLog
    QGIS_AVAILABLE = True
except ImportError:
    # QGIS 환경이 아닐 때는 더미 클래스 사용
    class QObject:
        def __init__(self):
            pass
    
    class pyqtSignal:
        def __init__(self, *args):
            pass
    
    class QgsMessageLog:
        @staticmethod
        def logMessage(message, tag="", level=None):
            print(f"[{tag}] {message}")
    
    QGIS_AVAILABLE = False


class MapServiceManager(QObject):
    """
    지도 서비스 설정을 관리하는 클래스
    - JSON 설정 파일에서 URL 정보 로드
    - 동적 URL 업데이트 지원
    - 실시간 설정 변경 감지
    """
    
    # 설정 변경 시그널
    serviceUpdated = pyqtSignal(str, str, str)  # service_name, layer_type, new_url
    
    def __init__(self, config_file_path=None):
        super().__init__()
        
        if config_file_path is None:
            # 기본 설정 파일 경로
            dir_path = os.path.dirname(__file__)
            config_file_path = os.path.join(dir_path, "config", "map_services.json")
        
        self.config_file_path = config_file_path
        self.config_data = {}
        self.load_config()

    @staticmethod
    def default_proxy_config():
        """최신 URL/가용성 테스트용 HTTP 프록시 설정(지도 타일 URL은 변경하지 않음)."""
        return {
            "enabled": False,
            "mode": "http_host",
            "http_host": "",
            "http_port": 8080,
            "http_user": "",
            "http_password": "",
            "url_get_template": "",
        }

    @staticmethod
    def default_tile_gateway_config():
        """QGIS/ OpenLayers가 실제로 요청하는 타일 URL에만 적용(저장된 원본 URL은 그대로)."""
        return {
            "enabled": False,
            "mode": "none",
            "prefix": "",
            "template": "",
            "encode_target": False,
        }

    @staticmethod
    def default_api_config():
        """최신 URL 업데이트용 API 키 설정."""
        return {
            "kakao_sdk_key": "",
        }
    
    def load_config(self):
        """설정 파일 로드"""
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
                QgsMessageLog.logMessage(f"Map service config loaded: {self.config_file_path}", "TMS for Korea")
            else:
                QgsMessageLog.logMessage(f"Config file not found: {self.config_file_path}", "TMS for Korea", QgsMessageLog.WARNING)
                self.config_data = {}
            if "_proxy" not in self.config_data:
                self.config_data["_proxy"] = dict(self.default_proxy_config())
            else:
                base = self.default_proxy_config()
                base.update(self.config_data["_proxy"])
                self.config_data["_proxy"] = base
            if "_tile_gateway" not in self.config_data:
                self.config_data["_tile_gateway"] = dict(self.default_tile_gateway_config())
            else:
                tg = self.default_tile_gateway_config()
                tg.update(self.config_data["_tile_gateway"])
                self.config_data["_tile_gateway"] = tg
            if "_api" not in self.config_data:
                self.config_data["_api"] = dict(self.default_api_config())
            else:
                api_cfg = self.default_api_config()
                api_cfg.update(self.config_data["_api"])
                self.config_data["_api"] = api_cfg
        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading config: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
            self.config_data = {
                "_proxy": self.default_proxy_config(),
                "_tile_gateway": self.default_tile_gateway_config(),
                "_api": self.default_api_config(),
            }

    def get_proxy_config(self):
        """프록시 설정(dict)."""
        return dict(self.config_data.get("_proxy", self.default_proxy_config()))

    def set_proxy_config(self, cfg):
        """프록시 설정 갱신 후 파일 저장."""
        merged = self.default_proxy_config()
        if isinstance(cfg, dict):
            merged.update(cfg)
        self.config_data["_proxy"] = merged
        self.save_config()

    def get_tile_gateway_config(self):
        """타일 요청 URL 게이트웨이(접두사/템플릿) 설정."""
        return dict(self.config_data.get("_tile_gateway", self.default_tile_gateway_config()))

    def merge_tile_gateway_config(self, cfg):
        """타일 게이트웨이 설정만 메모리에 반영(저장은 호출부에서 save_config 등)."""
        merged = self.default_tile_gateway_config()
        if isinstance(cfg, dict):
            merged.update(cfg)
        self.config_data["_tile_gateway"] = merged

    def get_api_config(self):
        """최신 URL 업데이트용 API 설정."""
        return dict(self.config_data.get("_api", self.default_api_config()))

    def merge_api_config(self, cfg):
        """API 설정만 메모리에 반영(저장은 호출부에서 save_config 등)."""
        merged = self.default_api_config()
        if isinstance(cfg, dict):
            merged.update(cfg)
        self.config_data["_api"] = merged

    def wrap_tile_url(self, url):
        """타일 한 줄 URL에 게이트웨이 적용. 설정 비활성·빈값이면 원본 그대로."""
        if not url or not isinstance(url, str):
            return url
        cfg = self.get_tile_gateway_config()
        if not cfg.get("enabled"):
            return url
        mode = (cfg.get("mode") or "none").lower()
        if mode in ("", "none", "off"):
            return url
        enc = bool(cfg.get("encode_target"))
        payload = urllib.parse.quote(url, safe="") if enc else url
        if mode == "prefix":
            p = (cfg.get("prefix") or "").strip()
            if not p:
                return url
            return p + payload
        if mode == "template":
            tpl = (cfg.get("template") or "").strip()
            if not tpl:
                return url
            if "{url}" in tpl:
                return tpl.replace("{url}", payload)
            if "{target_url}" in tpl:
                return tpl.replace("{target_url}", payload)
            return tpl + payload
        return url

    def wrap_tile_urls(self, urls):
        if not urls:
            return []
        return [self.wrap_tile_url(u) for u in urls]

    def get_map_service_names(self):
        """지도 서비스 이름만(예약 키 `_` 접두사 제외)."""
        return [k for k in self.config_data.keys() if not str(k).startswith("_")]
    
    def reload_config(self):
        """설정 파일 재로드"""
        self.load_config()
    
    def get_service_config(self, service_name, layer_type):
        """특정 서비스의 설정 가져오기"""
        try:
            return self.config_data.get(service_name, {}).get(layer_type, {})
        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting service config: {str(e)}", "TMS for Korea", QgsMessageLog.WARNING)
            return {}
    
    def get_urls(self, service_name, layer_type, for_tile_fetch=False):
        """특정 서비스의 URL 목록. for_tile_fetch=True이면 타일 게이트웨이(접두사/템플릿) 적용."""
        config = self.get_service_config(service_name, layer_type)
        urls = list(config.get("urls") or [])
        if for_tile_fetch:
            urls = self.wrap_tile_urls(urls)
        return urls
    
    def get_attribution(self, service_name, layer_type):
        """특정 서비스의 attribution 가져오기"""
        config = self.get_service_config(service_name, layer_type)
        return config.get('attribution', '')
    
    def get_version(self, service_name, layer_type):
        """특정 서비스의 버전 가져오기"""
        config = self.get_service_config(service_name, layer_type)
        return config.get('version', '')
    
    def update_service_urls(self, service_name, layer_type, new_urls):
        """서비스 URL 업데이트"""
        try:
            if service_name not in self.config_data:
                self.config_data[service_name] = {}
            
            if layer_type not in self.config_data[service_name]:
                self.config_data[service_name][layer_type] = {}
            
            self.config_data[service_name][layer_type]['urls'] = new_urls
            
            # 설정 파일 저장
            self.save_config()
            
            # 시그널 발생
            self.serviceUpdated.emit(service_name, layer_type, str(new_urls))
            
            QgsMessageLog.logMessage(f"Updated {service_name} {layer_type} URLs", "TMS for Korea")
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error updating service URLs: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
            return False
    
    def update_service_attribution(self, service_name, layer_type, new_attribution):
        """서비스 attribution 업데이트"""
        try:
            if service_name not in self.config_data:
                self.config_data[service_name] = {}
            
            if layer_type not in self.config_data[service_name]:
                self.config_data[service_name][layer_type] = {}
            
            self.config_data[service_name][layer_type]['attribution'] = new_attribution
            
            # 설정 파일 저장
            self.save_config()
            
            QgsMessageLog.logMessage(f"Updated {service_name} {layer_type} attribution", "TMS for Korea")
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(f"Error updating service attribution: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
            return False
    
    def save_config(self):
        """설정 파일 저장"""
        try:
            os.makedirs(os.path.dirname(self.config_file_path), exist_ok=True)
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error saving config: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
    
    def get_all_services(self):
        """모든 서비스 목록 반환"""
        return self.config_data
    
    def get_service(self, service_name):
        """특정 서비스 반환"""
        return self.config_data.get(service_name, {})
    
    def has_service(self, service_name):
        """서비스 존재 여부 확인"""
        return service_name in self.config_data
    
    def add_service(self, service_name, layer_name, urls, attribution, version):
        """새 서비스 추가"""
        if str(service_name).startswith("_"):
            raise ValueError("서비스 이름은 '_'로 시작할 수 없습니다.")
        if service_name not in self.config_data:
            self.config_data[service_name] = {}
        
        self.config_data[service_name][layer_name] = {
            'urls': urls,
            'attribution': attribution,
            'version': version
        }
    
    def update_service(self, service_name, layer_name, urls, attribution, version):
        """서비스 업데이트"""
        if str(service_name).startswith("_"):
            raise ValueError("서비스 이름은 '_'로 시작할 수 없습니다.")
        if service_name not in self.config_data:
            self.config_data[service_name] = {}
        
        self.config_data[service_name][layer_name] = {
            'urls': urls,
            'attribution': attribution,
            'version': version
        }
    
    def get_service_layers(self, service_name):
        """특정 서비스의 레이어 목록 반환(urls가 있는 항목만 — 메타 키 혼입 방지)."""
        svc = self.config_data.get(service_name, {})
        if not isinstance(svc, dict):
            return []
        return [
            k for k, v in svc.items()
            if isinstance(v, dict) and v.get("urls")
        ]
    
    def add_custom_service(self, service_name, layer_configs):
        """사용자 정의 서비스 추가"""
        try:
            if str(service_name).startswith("_"):
                raise ValueError("서비스 이름은 '_'로 시작할 수 없습니다.")
            self.config_data[service_name] = layer_configs
            self.save_config()
            QgsMessageLog.logMessage(f"Added custom service: {service_name}", "TMS for Korea")
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Error adding custom service: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
            return False
    
    def remove_service(self, service_name):
        """서비스 제거"""
        try:
            if str(service_name).startswith("_"):
                return False
            if service_name in self.config_data:
                del self.config_data[service_name]
                self.save_config()
                QgsMessageLog.logMessage(f"Removed service: {service_name}", "TMS for Korea")
                return True
            return False
        except Exception as e:
            QgsMessageLog.logMessage(f"Error removing service: {str(e)}", "TMS for Korea", QgsMessageLog.CRITICAL)
            return False
    
    def generate_js_layer_code(self, service_name, layer_type, layer_class_name):
        """JavaScript 레이어 코드 생성 (기본 - VWorld 등용)"""
        config = self.get_service_config(service_name, layer_type)
        urls = config.get('urls', [])
        if service_name == "daum_maps":
            urls = [self._kakao_5181_openlayers_tile_url(u) for u in urls]
        urls = [self.wrap_tile_url(u) for u in urls]
        attribution = config.get('attribution', '')

        urls_js = ",\n    ".join(
            f'"{self._escape_js_string(u)}"' for u in self._urls_for_openlayers_array(urls)
        )
        
        js_code = f"""
OpenLayers.Layer.{layer_class_name} = OpenLayers.Class(OpenLayers.Layer.XYZ, {{
    name: "{layer_class_name}",
    url: [
    {urls_js}
    ],
    attribution: '{attribution}',
    sphericalMercator: false,
    buffer: 1,
    numZoomLevels: 14,
    minResolution: 0.25,
    maxResolution: 2048,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:5181"),
    displayOutsideMaxExtent: true,
    maxExtent: new OpenLayers.Bounds(-30000, -60000, 494288, 988576),
    initialize: function(name, options) {{
        if (!options) options = {{resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25]}};
        else if (!options.resolutions) options.resolutions = [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25];
        var newArgs = [name, null, options];
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, newArgs);
    }},
    clone: function(obj) {{
        if (obj == null) {{
            obj = new OpenLayers.Layer.{layer_class_name}(
                this.name, this.getOptions());
        }}
        obj = OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
        return obj;
    }},
    getXYZ: function(bounds) {{
        var res = this.getServerResolution();
        var x = Math.round((bounds.left - this.maxExtent.left) / (res * this.tileSize.w));
        var y = Math.round((bounds.bottom - this.maxExtent.bottom) / (res * this.tileSize.h));
        var z = this.numZoomLevels - this.getServerZoom();
        if (this.wrapDateLine) {{
            var limit = Math.pow(2, z);
            x = ((x % limit) + limit) % limit;
        }}
        return {{'x': x, 'y': y, 'z': z}};
    }},
    CLASS_NAME: "OpenLayers.Layer.{layer_class_name}"
}});
"""
        return js_code

    @staticmethod
    def _urls_for_openlayers_array(urls):
        """
        map_services.json 등의 타일 URL을 OpenLayers.Layer.XYZ용으로 맞춤.
        - OpenLayers.String.format은 ${z}/${x}/${y}만 치환하므로 {z} 형은 ${z}로 변환
        - map{0-3}.daumcdn.net → map0..map3 네 줄로 펼침(서브도메인 로드 분산)
        """
        flat = []
        for raw in urls or []:
            u = str(raw)
            chunks = []
            if "{0-3}" in u or "${0-3}" in u:
                for i in range(4):
                    chunks.append(
                        u.replace("{0-3}", str(i)).replace("${0-3}", str(i))
                    )
            else:
                chunks.append(u)
            for p in chunks:
                t = p
                t = t.replace("${z}", "\x00Z\x00").replace("${x}", "\x00X\x00").replace(
                    "${y}", "\x00Y\x00"
                )
                t = t.replace("{z}", "${z}").replace("{x}", "${x}").replace("{y}", "${y}")
                t = (
                    t.replace("\x00Z\x00", "${z}")
                    .replace("\x00X\x00", "${x}")
                    .replace("\x00Y\x00", "${y}")
                )
                flat.append(t)
        return flat

    @staticmethod
    def _kakao_5181_openlayers_tile_url(url):
        """
        OpenLayers Daum getXYZ(x,y,z)와 카카오 타일 경로 정렬.
        번들 map*.daumcdn 레이어는 L${z}/${y}/${x} 를 쓰는데, MTS/SDK URL은
        .../latest/{z}/{x}/{y} 형이라 그대로 치환하면 행·열이 뒤바뀌어 지도가 깨짐.
        """
        s = str(url)
        if "mts.daumcdn.net" in s and "/latest/" in s:
            s = s.replace("${z}/${x}/${y}", "${z}/${y}/${x}")
            s = s.replace("{z}/{x}/{y}", "{z}/{y}/{x}")
        if "map_skyview" in s.lower():
            s = s.replace("L${z}/${x}/${y}", "L${z}/${y}/${x}")
            s = s.replace("L{z}/{x}/{y}", "L{z}/{y}/{x}")
        return s

    def generate_daum_js_layer_code(self, layer_type, layer_class_name):
        """카카오(다음) 지도용 JavaScript 레이어 코드 - EPSG:5181, getXYZ (Y flip 없음)"""
        config = self.get_service_config('daum_maps', layer_type)
        urls = config.get('urls', []) or ['http://map0.daumcdn.net/map_2d_hd/2204hep/L${z}/${y}/${x}.png']
        urls = [self._kakao_5181_openlayers_tile_url(u) for u in urls]
        urls = [self.wrap_tile_url(u) for u in urls]
        attribution = config.get('attribution', '') or '© Kakao'
        urls_js = self._urls_to_js(urls)
        return f"""
OpenLayers.Layer.{layer_class_name} = OpenLayers.Class(OpenLayers.Layer.XYZ, {{
    name: "{layer_class_name}",
    url: [
    {urls_js}
    ],
    resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25],
    attribution: "{self._escape_js_string(attribution)}",
    sphericalMercator: false,
    buffer: 1,
    numZoomLevels: 14,
    minResolution: 0.25,
    maxResolution: 2048,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:5181"),
    displayOutsideMaxExtent: true,
    maxExtent: new OpenLayers.Bounds(-30000, -60000, 494288, 988576),
    initialize: function(name, options) {{
        if (!options) options = {{resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25]}};
        else if (!options.resolutions) options.resolutions = [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25];
        var newArgs = [name, null, options];
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, newArgs);
    }},
    clone: function(obj) {{
        if (obj == null) obj = new OpenLayers.Layer.{layer_class_name}(this.name, this.getOptions());
        obj = OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
        return obj;
    }},
    getXYZ: function(bounds) {{
        var res = this.getServerResolution();
        var x = Math.round((bounds.left - this.maxExtent.left) / (res * this.tileSize.w));
        var y = Math.round((bounds.bottom - this.maxExtent.bottom) / (res * this.tileSize.h));
        var z = this.numZoomLevels - this.getServerZoom();
        if (this.wrapDateLine) {{
            var limit = Math.pow(2, z);
            x = ((x % limit) + limit) % limit;
        }}
        return {{'x': x, 'y': y, 'z': z}};
    }},
    CLASS_NAME: "OpenLayers.Layer.{layer_class_name}"
}});
"""

    def _escape_js_string(self, s):
        """JavaScript 문자열 이스케이프"""
        if not s:
            return ''
        return str(s).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '\\n')

    def _urls_to_js(self, urls):
        """URL 리스트를 JS 배열 문자열로 변환"""
        return ",\n    ".join(
            f'"{self._escape_js_string(u)}"' for u in self._urls_for_openlayers_array(urls)
        )

    def generate_naver_3857_js_layer_code(self, layer_type, layer_class_name):
        """네이버 nrb 타일 - EPSG:3857 (Web Mercator), sphericalMercator"""
        config = self.get_service_config('naver_maps', layer_type)
        urls = config.get('urls', [])
        attribution = config.get('attribution', '') or '© NHN Corp.'
        url = urls[0] if urls else 'https://map.pstatic.net/nrb/styles/basic/default/${z}/${x}/${y}.jpg'
        url = self._urls_for_openlayers_array([url])[0]
        url = self.wrap_tile_url(url)
        return f"""
OpenLayers.Layer.{layer_class_name} = OpenLayers.Class(OpenLayers.Layer.XYZ, {{
    name: "{layer_class_name}",
    url: ["{self._escape_js_string(url)}"],
    attribution: "{self._escape_js_string(attribution)}",
    sphericalMercator: true,
    wrapDateLine: true,
    numZoomLevels: 19,
    maxResolution: 156543.0339,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:3857"),
    maxExtent: new OpenLayers.Bounds(-20037508.34, -20037508.34, 20037508.34, 20037508.34),
    initialize: function(name, options) {{
        options = options || {{}};
        if (options.layerUrl) {{ this.url = [options.layerUrl]; delete options.layerUrl; }}
        options.resolutions = options.resolutions || (function() {{
            var res = []; for (var z = 0; z <= 18; z++) res.push(156543.0339 / Math.pow(2, z)); return res;
        }})();
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, [name, this.url, options]);
    }},
    clone: function(obj) {{
        if (!obj) obj = new OpenLayers.Layer.{layer_class_name}(this.name, this.getOptions());
        return OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
    }},
    CLASS_NAME: "OpenLayers.Layer.{layer_class_name}"
}});
"""

    def generate_naver_5179_js_layer_code(self, layer_type, layer_class_name):
        """네이버 지도용 - EPSG:5179, proj4 5179->3857 변환 (Naver5179_getXYZ 사용)"""
        config = self.get_service_config('naver_maps', layer_type)
        urls = config.get('urls', []) or ['https://map.pstatic.net/nrb/styles/basic/default/${z}/${x}/${y}.jpg']
        attribution = config.get('attribution', '') or '© NHN Corp.'
        urls = [self.wrap_tile_url(u) for u in urls]
        urls_js = self._urls_to_js(urls)
        return f"""
OpenLayers.Layer.{layer_class_name} = OpenLayers.Class(OpenLayers.Layer.XYZ, {{
    name: "{layer_class_name}",
    url: [{urls_js}],
    attribution: "{self._escape_js_string(attribution)}",
    sphericalMercator: false,
    buffer: 1,
    numZoomLevels: 14,
    minResolution: 0.5,
    maxResolution: 2048,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:5179"),
    displayOutsideMaxExtent: false,
    maxExtent: new OpenLayers.Bounds(90112, 1192896, 1990673, 2761664),
    initialize: function(name, options) {{
        if (!options) options = {{resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25]}};
        else if (!options.resolutions) options.resolutions = [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25];
        var newArgs = [name, null, options];
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, newArgs);
    }},
    clone: function(obj) {{
        if (obj == null) obj = new OpenLayers.Layer.{layer_class_name}(this.name, this.getOptions());
        obj = OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
        return obj;
    }},
    getXYZ: function(bounds) {{ return OpenLayers.Layer.Naver5179_getXYZ.call(this, bounds); }},
    CLASS_NAME: "OpenLayers.Layer.{layer_class_name}"
}});
"""

    def _vworld_default_url(self, layer_type):
        """VWorld 기본 URL"""
        types = {'street': 'Base', 'satellite': 'Satellite', 'gray': 'white', 'hybrid': 'Hybrid'}
        t = types.get(layer_type, 'Base')
        ext = 'png' if layer_type != 'satellite' else 'jpeg'
        return f'https://xdworld.vworld.kr/2d/{t}/service/${{z}}/${{x}}/${{y}}.{ext}'

    def generate_vworld_js_layer_code(self, layer_type, layer_class_name):
        """VWorld 지도용 - EPSG:3857, sphericalMercator"""
        config = self.get_service_config('vworld_maps', layer_type)
        urls = config.get('urls') or [self._vworld_default_url(layer_type)]
        urls = [self.wrap_tile_url(u) for u in urls]
        attribution = config.get('attribution', '') or '© VWorld'
        urls_js = self._urls_to_js(urls)
        return f"""
OpenLayers.Layer.{layer_class_name} = OpenLayers.Class(OpenLayers.Layer.XYZ, {{
    name: "{layer_class_name}",
    url: [{urls_js}],
    attribution: "{self._escape_js_string(attribution)}",
    sphericalMercator: true,
    wrapDateLine: true,
    buffer: 1,
    numZoomLevels: 19,
    maxResolution: 156543.0339,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:3857"),
    maxExtent: new OpenLayers.Bounds(-20037508.34, -20037508.34, 20037508.34, 20037508.34),
    initialize: function(name, options) {{
        options = options || {{}};
        options.resolutions = options.resolutions || (function() {{
            var res = []; for (var z = 0; z <= 18; z++) res.push(156543.0339 / Math.pow(2, z)); return res;
        }})();
        var newArgs = [name, this.url, options];
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, newArgs);
    }},
    clone: function(obj) {{
        if (!obj) obj = new OpenLayers.Layer.{layer_class_name}(this.name, this.getOptions());
        return OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
    }},
    CLASS_NAME: "OpenLayers.Layer.{layer_class_name}"
}});
"""

    def generate_vworld_hybrid_init_js(self):
        """VWorld Hybrid - 위성+하이브리드 2개 레이어 추가"""
        hyb_config = self.get_service_config('vworld_maps', 'hybrid')
        hyb_urls = hyb_config.get('urls', []) or [
            'https://xdworld.vworld.kr/2d/Satellite/service/${z}/${x}/${y}.jpeg',
            'https://xdworld.vworld.kr/2d/Hybrid/service/${z}/${x}/${y}.png',
        ]
        hyb_norm = self._urls_for_openlayers_array(hyb_urls)
        sat_url = self.wrap_tile_url(hyb_norm[0] if hyb_norm else '')
        hyb_url = self.wrap_tile_url(hyb_norm[1] if len(hyb_norm) > 1 else hyb_norm[0] if hyb_norm else '')
        attribution = hyb_config.get('attribution', '') or '© VWorld'
        sat_url_esc = self._escape_js_string(sat_url)
        hyb_url_esc = self._escape_js_string(hyb_url)
        attr_esc = self._escape_js_string(attribution)
        return f"""
    var opts = {{ resolutions: (function() {{ var r=[]; for(var z=0;z<=18;z++) r.push(156543.0339/Math.pow(2,z)); return r; }})() }};
    var vWorldSat = new OpenLayers.Layer.XYZ("VWorld Satellite", ["{sat_url_esc}"], {{ sphericalMercator: true, wrapDateLine: true, attribution: "{attr_esc}", resolutions: opts.resolutions }});
    var vWorldHyb = new OpenLayers.Layer.XYZ("VWorld Hybrid", ["{hyb_url_esc}"], {{ sphericalMercator: true, wrapDateLine: true, resolutions: opts.resolutions }});
    map.addLayers([vWorldSat, vWorldHyb]);
""" 