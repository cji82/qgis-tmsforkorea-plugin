/**
 * 네이버 nrb 타일 - EPSG:3857 (Web Mercator) 전용
 * nrb API가 Web Mercator 타일만 제공하므로 3857 사용
 * options.layerUrl: 타일 URL (기본: basic/street)
 */
OpenLayers.Layer.Naver3857 = OpenLayers.Class(OpenLayers.Layer.XYZ, {
    name: "NaverMap3857",
    url: ["https://map.pstatic.net/nrb/styles/basic/1778232861/${z}/${x}/${y}.jpg"],
    attribution: '<a href="http://www.nhncorp.com" target="_blank">© NHN Corp.</a>',
    sphericalMercator: true,
    wrapDateLine: true,
    numZoomLevels: 19,
    maxResolution: 156543.0339,
    units: "m",
    projection: new OpenLayers.Projection("EPSG:3857"),
    maxExtent: new OpenLayers.Bounds(-20037508.34, -20037508.34, 20037508.34, 20037508.34),
    initialize: function(name, options) {
        options = options || {};
        if (options.layerUrl) {
            this.url = [options.layerUrl];
            delete options.layerUrl;
        }
        options.resolutions = options.resolutions || (function() {
            var res = [];
            for (var z = 0; z <= 18; z++) {
                res.push(156543.0339 / Math.pow(2, z));
            }
            return res;
        })();
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, [name, this.url, options]);
    },
    clone: function(obj) {
        if (!obj) obj = new OpenLayers.Layer.Naver3857(this.name, this.getOptions());
        return OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
    },
    setUrl: function(url) {
        this.url = [url];
    },
    CLASS_NAME: "OpenLayers.Layer.Naver3857"
});
