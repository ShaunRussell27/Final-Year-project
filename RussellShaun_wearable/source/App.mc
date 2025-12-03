// This file is intentionally left blank.
using Toybox.Application as AppBase;
using Toybox.WatchUi as WatchUi;
using Toybox.Sensor as Sensor;
using Toybox.System as Sys;

class MyFirstGarminApp extends AppBase.Application {

    function initialize() {
        AppBase.Application.initialize();
    }

    function onStart(state) {
        WatchUi.pushView(new MyFirstGarminView(), WatchUi.SLIDE_IMMEDIATE);
    }
}

class MyFirstGarminView extends WatchUi.View {

    function onUpdate(dc) {
        dc.clear();
        dc.drawText(
            dc.getWidth()/2,
            dc.getHeight()/2,
            WatchUi.FONT_XLARGE,
            "HELLO GARMIN!",
            WatchUi.TEXT_JUSTIFY_CENTER
        );
    }
}

var filePath = "/DATA/burnout_data.json";
var dataArray = [];

function onTimer() {
    var info = Sensor.getInfo();
    if (info != null) {
        var entry = {
            "time"   => Sys.getEpoch(),
            "hr"     => info.currentHeartRate,
            "stress" => info.stress
        };

        dataArray += [entry];

        // Write entire array to file
        Sys.writeFile(Sys.Storage.FILE, filePath, dataArray);
    }
}

function initialize() {
    WatchUi.WatchFace.initialize();
    Sys.setTimer(30000, method(:onTimer));
}

