/* Copyright (c) 2006-2012 by OpenLayers Contributors (see authors.txt for 
 * full list of contributors). Published under the 2-clause BSD license.
 * See license.txt in the OpenLayers distribution or repository for the
 * full text of the license. */

/**
 * @requires OpenLayers/Layer/XYZ.js
 */

OpenLayers.Layer.NaverCadstral = OpenLayers.Class(OpenLayers.Layer.XYZ, {
  
    name: "NaverCadstralMap",
    url: [
    "https://map.pstatic.net/nrb/styles/basic/1778232861/${z}/${x}/${y}.jpg?mt=bg.ol.ts.lp"
    ],
  resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25],
  attribution: '<a href="http://www.nhncorp.com" target="_blank" style="text-decoration: none !important;">© <span style="display: inline; font-family: Tahoma,sans-serif !important; font-size: 9px !important; font-weight: bold !important; font-style: normal !important; color: #009BC8 !important; text-decoration: none !important;">'
    + 'NHN Corp.</span></a>'
    + '<img class="nmap_logo_map" src="http://static.naver.net/maps2/logo_naver_s.png" width="43" height="9" alt="NAVER">',
  sphericalMercator: false,
  transitionEffect: "resize",
  buffer: 1,
  numZoomLevels: 14,
  minResolution: 0.5,
  maxResolution: 2048,
  units: "m",
  projection: new OpenLayers.Projection("EPSG:5179"),
  displayOutsideMaxExtent: false,
  maxExtent: new OpenLayers.Bounds(90112, 1192896, 1990673, 2761664),
    initialize: function(name, options) {
    if (!options) options = {resolutions: [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25]};
    else if (!options.resolutions) options.resolutions = [2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25];
        var newArgs = [name, null, options];
        OpenLayers.Layer.XYZ.prototype.initialize.apply(this, newArgs);
    },
    clone: function(obj) {
        if (obj == null) {
            obj = new OpenLayers.Layer.NaverCadstral(
                this.name, this.getOptions());
        }
        obj = OpenLayers.Layer.XYZ.prototype.clone.apply(this, [obj]);
        return obj;
    },

  getXYZ: function(bounds) {
    return OpenLayers.Layer.Naver5179_getXYZ.call(this, bounds);
  },
  CLASS_NAME: "OpenLayers.Layer.NaverCadstral"
});
