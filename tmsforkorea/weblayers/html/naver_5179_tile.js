/**
 * 네이버 nrb 타일 - EPSG:5179 프로젝트용 (5179 타일 → Mercator z/x/y)
 * z는 타일 경계마다 log로 구하면 이웃 타일이 서로 다른 z를 쓰며 줄이 어긋남 → map.getZoom()으로만 결정.
 * proj4 EPSG:5179 정의는 proj4_5179.js에만 둔다(이중 정의 금지).
 */
(function() {
    if (typeof proj4 === 'undefined') {
        OpenLayers.Layer.Naver5179_getXYZ = function() { return {x: 28000, y: 12700, z: 14}; };
        return;
    }

    var origin3857 = -20037508.34;
    var worldSize = 40075016.68;

    OpenLayers.Layer.Naver5179_getXYZ = function(bounds) {
        var map = this.map;
        var iz = (map && typeof map.getZoom === 'function') ? map.getZoom() : 7;
        if (iz < 0) {
            iz = 0;
        }
        var maxOl = (map && typeof map.getNumZoomLevels === 'function') ? (map.getNumZoomLevels() - 1) : 13;
        if (iz > maxOl) {
            iz = maxOl;
        }
        /* naver_street_5179 등: OL 줌 0(2048m/px) ≈ nrb z6, 상한 18 */
        var z = 6 + iz;
        if (z > 18) {
            z = 18;
        }
        if (z < 0) {
            z = 0;
        }

        var tileW = worldSize / Math.pow(2, z);
        var cx = (bounds.left + bounds.right) / 2;
        var cy = (bounds.bottom + bounds.top) / 2;
        var center = proj4('EPSG:5179', 'EPSG:3857', [cx, cy]);
        if (!center || isNaN(center[0]) || isNaN(center[1])) {
            return {x: 28000, y: 12700, z: z};
        }
        var x = Math.floor((center[0] - origin3857) / tileW);
        var y = Math.floor((origin3857 + worldSize - center[1]) / tileW);
        var limit = Math.pow(2, z);
        x = Math.max(0, Math.min(limit - 1, x));
        y = Math.max(0, Math.min(limit - 1, y));
        return {x: x, y: y, z: z};
    };
})();
