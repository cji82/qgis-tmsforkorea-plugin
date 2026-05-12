/**
 * EPSG:5179 (Korea 2000 / Unified CS) 정의 및 OpenLayers 변환 등록
 * 5179 <-> 4326 <-> 3857 변환 지원 (nrb 타일용)
 */
(function() {
    if (typeof proj4 === 'undefined') return;
    var def = '+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 +units=m +no_defs';
    proj4.defs('EPSG:5179', def);

    function transformPoint(point, from, to) {
        var c = proj4(from, to, [point.x, point.y]);
        point.x = c[0];
        point.y = c[1];
    }

    OpenLayers.Projection.addTransform('EPSG:5179', 'EPSG:4326', function(p) { transformPoint(p, 'EPSG:5179', 'EPSG:4326'); });
    OpenLayers.Projection.addTransform('EPSG:4326', 'EPSG:5179', function(p) { transformPoint(p, 'EPSG:4326', 'EPSG:5179'); });
    OpenLayers.Projection.addTransform('EPSG:5179', 'EPSG:3857', function(p) { transformPoint(p, 'EPSG:5179', 'EPSG:3857'); });
    OpenLayers.Projection.addTransform('EPSG:3857', 'EPSG:5179', function(p) { transformPoint(p, 'EPSG:3857', 'EPSG:5179'); });
})();
