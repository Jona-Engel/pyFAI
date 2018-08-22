# coding: utf-8
# /*##########################################################################
#
# Copyright (C) 2016-2018 European Synchrotron Radiation Facility
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# ###########################################################################*/

from __future__ import absolute_import

__authors__ = ["V. Valls"]
__license__ = "MIT"
__date__ = "22/08/2018"

import logging
import numpy
import collections
import functools

from silx.gui import qt
import silx.gui.plot
import silx.gui.icons
import silx.io

import pyFAI.utils
from pyFAI.gui.calibration.AbstractCalibrationTask import AbstractCalibrationTask
from pyFAI.azimuthalIntegrator import AzimuthalIntegrator
from . import utils
from .model.DataModel import DataModel
from ..widgets.QuantityLabel import QuantityLabel
from .CalibrationContext import CalibrationContext
from .model import MarkerModel
from . import units

_logger = logging.getLogger(__name__)


class EnablableDataModel(DataModel):

    def __init__(self, parent, model):
        DataModel.__init__(self, parent=parent)
        self.__model = model
        self.__model.changed.connect(self.__modelChanged)
        self.__isEnabled = False
        self.__modelChanged()

    def setEnabled(self, isEnabled):
        if self.__isEnabled == isEnabled:
            return
        self.__isEnabled = isEnabled
        if self.__isEnabled:
            self.__model.setValue(self.value())
        else:
            self.__model.setValue(None)
        self.wasChanged()

    def isEnabled(self):
        return self.__isEnabled

    def __modelChanged(self):
        value = self.__model.value()
        if self.value() == value:
            return
        self.lockSignals()
        self.setEnabled(value is not None)
        if value is not None:
            self.setValue(value)
        self.unlockSignals()

    def setValue(self, value):
        super(EnablableDataModel, self).setValue(value)
        if self.__isEnabled:
            self.__model.setValue(value)


class IntegrationProcess(object):

    def __init__(self, model):
        self.__isValid = self._init(model)

    def _init(self, model):
        self.__isValid = True
        if model is None:
            return False
        image = model.experimentSettingsModel().image().value()
        if image is None:
            return False
        mask = model.experimentSettingsModel().mask().value()
        detector = model.experimentSettingsModel().detector()
        if detector is None:
            return
        geometry = model.fittedGeometry()
        if not geometry.isValid():
            return False
        self.__radialUnit = model.integrationSettingsModel().radialUnit().value()
        if self.__radialUnit is None:
            return False
        self.__polarizationFactor = model.experimentSettingsModel().polarizationFactor().value()

        self.__calibrant = model.experimentSettingsModel().calibrantModel().calibrant()

        if mask is not None:
            mask = numpy.array(mask)
        if image is not None:
            image = numpy.array(image)

        # FIXME calibrant and detector have to be cloned
        self.__detector = detector
        self.__image = image
        self.__mask = mask

        self.__wavelength = geometry.wavelength().value()
        self.__distance = geometry.distance().value()
        self.__poni1 = geometry.poni1().value()
        self.__poni2 = geometry.poni2().value()
        self.__rotation1 = geometry.rotation1().value()
        self.__rotation2 = geometry.rotation2().value()
        self.__rotation3 = geometry.rotation3().value()
        return True

    def isValid(self):
        return self.__isValid

    def run(self):
        ai = AzimuthalIntegrator(
            dist=self.__distance,
            poni1=self.__poni1,
            poni2=self.__poni2,
            rot1=self.__rotation1,
            rot2=self.__rotation2,
            rot3=self.__rotation3,
            detector=self.__detector,
            wavelength=self.__wavelength)

        numberPoint1D = 1024
        numberPointRadial = 400
        numberPointAzimuthal = 360

        # FIXME error model, method

        self.__result1d = ai.integrate1d(
            data=self.__image,
            npt=numberPoint1D,
            unit=self.__radialUnit,
            mask=self.__mask,
            polarization_factor=self.__polarizationFactor)

        self.__result2d = ai.integrate2d(
            data=self.__image,
            npt_rad=numberPointRadial,
            npt_azim=numberPointAzimuthal,
            unit=self.__radialUnit,
            mask=self.__mask,
            polarization_factor=self.__polarizationFactor)

        if self.__calibrant:

            rings = self.__calibrant.get_2th()
            rings = filter(lambda x: x <= self.__result1d.radial[-1], rings)
            rings = list(rings)
            try:
                rings = utils.from2ThRad(rings, self.__radialUnit, self.__wavelength, ai)
            except ValueError:
                message = "Convertion to unit %s not supported. Ring marks ignored"
                _logger.warning(message, self.__radialUnit)
                rings = []
        else:
            rings = []
        self.__ringAngles = rings

        self.__ai = ai

        try:
            self.__directDist = ai.getFit2D()["directDist"]
        except Exception:
            # The geometry could not fit this param
            _logger.debug("Backtrace", exc_info=True)
            self.__directDist = None

    def ringAngles(self):
        return self.__ringAngles

    def result1d(self):
        return self.__result1d

    def result2d(self):
        return self.__result2d

    def radialUnit(self):
        return self.__radialUnit

    def wavelength(self):
        return self.__wavelength

    def directDist(self):
        return self.__directDist

    def geometry(self):
        """
        :rtype: pyFAI.geometry.Geometry
        """
        return self.__ai


def createSaveDialog(parent, title, poni=False, json=False, csv=False):
    """Util to create create a save dialog"""
    dialog = CalibrationContext.instance().createFileDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setAcceptMode(qt.QFileDialog.AcceptSave)

    extensions = collections.OrderedDict()
    if poni:
        extensions["PONI files"] = "*.poni"
    if json:
        extensions["JSON files"] = "*.json"
    if csv:
        extensions["CSV files"] = "*.csv"

    filters = []
    filters.append("All supported files (%s)" % " ".join(extensions.values()))
    for name, extension in extensions.items():
        filters.append("%s (%s)" % (name, extension))
    filters.append("All files (*)")

    dialog.setNameFilters(filters)
    return dialog


class _StatusBar(qt.QStatusBar):

    def __init__(self, parent=None):
        qt.QStatusBar.__init__(self, parent)

        angleUnitModel = CalibrationContext.instance().getAngleUnit()

        self.__chi = QuantityLabel(self)
        self.__chi.setPrefix(u"<b>χ</b>: ")
        self.__chi.setFormatter(u"{value}")
        self.__chi.setInternalUnit(units.Unit.RADIAN)
        self.__chi.setDisplayedUnit(units.Unit.RADIAN)
        self.__chi.setDisplayedUnitModel(angleUnitModel)
        self.__chi.setUnitEditable(True)
        self.addWidget(self.__chi)
        self.__2theta = QuantityLabel(self)
        self.__2theta.setPrefix(u"<b>2θ</b>: ")
        self.__2theta.setFormatter(u"{value}")
        self.__2theta.setInternalUnit(units.Unit.RADIAN)
        self.__2theta.setDisplayedUnitModel(angleUnitModel)
        self.__2theta.setUnitEditable(True)
        self.addWidget(self.__2theta)

        self.clearValues()

    def setValue(self, tth):
        self.__chi.setVisible(False)
        self.__2theta.setVisible(True)
        self.__2theta.setValue(tth)

    def setValues(self, chi, tth):
        self.__chi.setVisible(True)
        self.__2theta.setVisible(True)
        self.__chi.setValue(chi)
        self.__2theta.setValue(tth)

    def clearValues(self):
        self.__chi.setVisible(False)
        self.__2theta.setValue(float("nan"))


class MarkerManager(object):

    def __init__(self, plot, markerModel):
        self.__plot = plot
        self.__markerModel = markerModel
        self.__markerModel.changed.connect(self.__updateMarkers)
        self.__geometry = None
        self.__markers = []

    def updateProjection(self, geometry, radialUnit, wavelength, directDist):
        self.__geometry = geometry
        self.__radialUnit = radialUnit
        self.__wavelength = wavelength
        self.__directDist = directDist
        self.__updateMarkers()

    def __updateMarkers(self):
        for item in self.__markers:
            self.__plot.removeMarker(item.getLegend())

        template = "__markers__%s"

        for marker in self.__markerModel:
            if isinstance(marker, MarkerModel.PhysicalMarker):
                chiRad, tthRad = marker.physicalPosition()
            elif isinstance(marker, MarkerModel.PixelMarker):
                x, y = marker.pixelPosition()
                ax, ay = numpy.array([x]), numpy.array([y])
                chiRad = self.__geometry.chi(ay, ax)[0]
                tthRad = self.__geometry.tth(ay, ax)[0]
            else:
                _logger.debug("Unsupported logger %s", type(marker))
                continue

            tth = utils.from2ThRad(tthRad,
                                   unit=self.__radialUnit,
                                   wavelength=self.__wavelength,
                                   directDist=self.__directDist)
            chi = numpy.rad2deg(chiRad)

            legend = template % marker.name()
            self.__plot.addMarker(x=tth, y=chi, color="pink", legend=legend, text=marker.name())
            item = self.__plot._getMarker(legend)
            self.__markers.append(item)


class IntegrationPlot(qt.QFrame):

    def __init__(self, parent=None):
        super(IntegrationPlot, self).__init__(parent)

        self.__plot1d, self.__plot2d = self.__createPlots(self)
        self.__statusBar = _StatusBar(self)
        self.__statusBar.setSizeGripEnabled(False)

        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(self.__plot2d)
        layout.addWidget(self.__plot1d)
        layout.addWidget(self.__statusBar)
        self.__setResult(None)
        self.__processing1d = None
        self.__processing2d = None
        self.__ringItems = {}
        self.__axisOfCurrentView = None
        self.__markerColors = {}
        self.__angleUnderMouse = None
        self.__availableRingAngles = None
        self.__radialUnit = None
        self.__wavelength = None
        self.__directDist = None
        self.__geometry = None

        markerModel = CalibrationContext.instance().getCalibrationModel().markerModel()
        self.__markerManager = MarkerManager(self.__plot2d, markerModel)

        self.__plot2d.getXAxis().sigLimitsChanged.connect(self.__axesChanged)
        self.__plot1d.sigPlotSignal.connect(self.__plot1dSignalReceived)
        self.__plot2d.sigPlotSignal.connect(self.__plot2dSignalReceived)

        widget = self.__plot1d
        if hasattr(widget, "centralWidget"):
            widget.centralWidget()
        widget.installEventFilter(self)
        widget = self.__plot2d
        if hasattr(widget, "centralWidget"):
            widget.centralWidget()
        widget.installEventFilter(self)

        colormap = CalibrationContext.instance().getRawColormap()
        self.__plot2d.setDefaultColormap(colormap)

        from silx.gui.plot.utils.axis import SyncAxes
        self.__syncAxes = SyncAxes([self.__plot1d.getXAxis(), self.__plot2d.getXAxis()])

    def aboutToClose(self):
        # Avoid double free release problem. See #892
        self.__syncAxes.stop()
        self.__syncAxes = None

    def resetZoom(self):
        self.__plot2d.resetZoom()
        self.__plot1d.resetZoom()

    def eventFilter(self, widget, event):
        if event.type() == qt.QEvent.Leave:
            self.__mouseLeave()
            return True
        return False

    def __mouseLeave(self):
        self.__statusBar.clearValues()

        if self.__angleUnderMouse is None:
            return
        if self.__angleUnderMouse not in self.__displayedAngles:
            items = self.__ringItems.get(self.__angleUnderMouse, [])
            for item in items:
                item.setVisible(False)
        self.__angleUnderMouse = None

    def __plot1dSignalReceived(self, event):
        """Called when old style signals at emmited from the plot."""
        if event["event"] == "mouseMoved":
            x, y = event["x"], event["y"]
            self.__mouseMoved(x, y)
            self.__updateStatusBar(x, None)

    def __plot2dSignalReceived(self, event):
        """Called when old style signals at emmited from the plot."""
        if event["event"] == "mouseMoved":
            x, y = event["x"], event["y"]
            self.__mouseMoved(x, y)
            self.__updateStatusBar(x, y)

    def __getClosestAngle(self, angle):
        """
        Returns the closest ring index and ring angle
        """
        # TODO: Could be done in log(n) using bisect search
        result = None
        iresult = None
        minDistance = float("inf")
        for ringId, ringAngle in enumerate(self.__availableRingAngles):
            distance = abs(angle - ringAngle)
            if distance < minDistance:
                minDistance = distance
                result = ringAngle
                iresult = ringId
        return iresult, result

    def dataToChiTth(self, data):
        """Returns chi and 2theta angles in radian from data coordinate"""
        try:
            tthRad = utils.tthToRad(data[0],
                                    unit=self.__radialUnit,
                                    wavelength=self.__wavelength,
                                    directDist=self.__directDist)
        except Exception:
            _logger.debug("Backtrace", exc_info=True)
            tthRad = None

        chiDeg = data[1]
        if chiDeg is not None:
            chiRad = numpy.deg2rad(chiDeg)
        else:
            chiRad = None

        return chiRad, tthRad

    def __updateStatusBar(self, x, y):
        chiRad, tthRad = self.dataToChiTth((x, y))
        if tthRad is not None and chiRad is not None:
            self.__statusBar.setValues(chiRad, tthRad)
        elif tthRad is not None:
            self.__statusBar.setValue(tthRad)
        else:
            self.__statusBar.clearValues()

    def __mouseMoved(self, x, y):
        """Called when mouse move over the plot."""
        if self.__availableRingAngles is None:
            return
        angle = x
        ringId, angle = self.__getClosestAngle(angle)

        if angle == self.__angleUnderMouse:
            return

        if self.__angleUnderMouse not in self.__displayedAngles:
            items = self.__ringItems.get(self.__angleUnderMouse, [])
            for item in items:
                item.setVisible(False)

        self.__angleUnderMouse = angle

        if angle is not None:
            items = self.__getItemsFromAngle(ringId, angle)
            for item in items:
                item.setVisible(True)

    def __axesChanged(self, minValue, maxValue):
        axisOfCurrentView = self.__plot2d.getXAxis().getLimits()
        if self.__axisOfCurrentView == axisOfCurrentView:
            return
        self.__updateRings()

    def markerColorList(self):
        colormap = self.getDefaultColormap()

        name = colormap['name']
        if name not in self.__markerColors:
            colors = self.createMarkerColors()
            self.__markerColors[name] = colors
        else:
            colors = self.__markerColors[name]
        return colors

    def createMarkerColors(self):
        colormap = self.getDefaultColormap()
        return utils.getFreeColorRange(colormap)

    def __getAvailableAngles(self, minTth, maxTth):
        result = []
        for ringId, angle in enumerate(self.__availableRingAngles):
            if minTth is None or maxTth is None:
                result.append(ringId, angle)
            if minTth <= angle <= maxTth:
                result.append((ringId, angle))
        return result

    def __updateRings(self):
        minTth, maxTth = self.__plot2d.getXAxis().getLimits()
        angles = self.__getAvailableAngles(minTth, maxTth)

        if len(angles) < 20:
            step = 1
        elif len(angles) < 100:
            step = 2
        elif len(angles) < 200:
            step = 5
        elif len(angles) < 500:
            step = 10
        elif len(angles) < 1000:
            step = 20
        elif len(angles) < 5000:
            step = 100
        else:
            step = int(len(angles) / 50)

        self.__displayedAngles = set([])

        for items in self.__ringItems.values():
            for item in items:
                item.setVisible(False)

        for angleId in range(0, len(angles), step):
            ringId, ringAngle = angles[angleId]
            self.__displayedAngles.add(ringAngle)
            items = self.__getItemsFromAngle(ringId, ringAngle)
            for item in items:
                item.setVisible(True)

    def __getItemsFromAngle(self, ringId, ringAngle):
        items = self.__ringItems.get(ringAngle, None)
        if items is not None:
            return items

        colors = self.markerColorList()
        color = colors[ringId % len(colors)]
        numpyColor = numpy.array([color.redF(), color.greenF(), color.blueF()])
        items = []

        legend = "ring-%i" % (ringId,)

        self.__plot1d.addXMarker(x=ringAngle, color=numpyColor, legend=legend)
        item = self.__plot1d._getMarker(legend)
        items.append(item)

        self.__plot2d.addXMarker(x=ringAngle, color=numpyColor, legend=legend)
        item = self.__plot2d._getMarker(legend)
        items.append(item)

        self.__ringItems[ringAngle] = items
        return items

    def __syncModeToPlot1d(self, _event):
        modeDict = self.__plot2d.getInteractiveMode()
        mode = modeDict["mode"]
        self.__plot1d.setInteractiveMode(mode)

    def getDefaultColormap(self):
        return self.__plot2d.getDefaultColormap()

    def __createPlots(self, parent):
        plot1d = silx.gui.plot.PlotWidget(parent)
        plot1d.setGraphXLabel("Radial")
        plot1d.setGraphYLabel("Intensity")
        plot1d.setGraphGrid(False)
        plot2d = silx.gui.plot.PlotWidget(parent)
        plot2d.setGraphXLabel("Radial")
        plot2d.setGraphYLabel("Azimuthal")
        plot2d.sigInteractiveModeChanged.connect(self.__syncModeToPlot1d)

        handle = plot2d.getWidgetHandle()
        handle.setContextMenuPolicy(qt.Qt.CustomContextMenu)
        handle.customContextMenuRequested.connect(self.__plot2dContextMenu)

        from silx.gui.plot import tools
        toolBar = tools.InteractiveModeToolBar(parent=self, plot=plot2d)
        plot2d.addToolBar(toolBar)

        toolBar = tools.ImageToolBar(parent=self, plot=plot2d)
        colormapDialog = CalibrationContext.instance().getColormapDialog()
        toolBar.getColormapAction().setColorDialog(colormapDialog)
        previousResetZoomAction = toolBar.getResetZoomAction()
        resetZoomAction = qt.QAction()
        resetZoomAction.triggered.connect(self.resetZoom)
        resetZoomAction.setIcon(previousResetZoomAction.icon())
        resetZoomAction.setText(previousResetZoomAction.text())
        resetZoomAction.setToolTip(previousResetZoomAction.toolTip())
        toolBar.insertAction(previousResetZoomAction, resetZoomAction)
        previousResetZoomAction.setVisible(False)
        self.__resetZoomAction = resetZoomAction
        plot2d.addToolBar(toolBar)

        ownToolBar = qt.QToolBar(plot2d)
        from silx.gui.plot import actions
        logAction = actions.control.YAxisLogarithmicAction(parent=ownToolBar, plot=plot1d)
        logAction.setToolTip("Logarithmic y-axis intensity when checked")
        ownToolBar.addAction(logAction)
        plot2d.addToolBar(ownToolBar)

        action = qt.QAction(ownToolBar)
        action.setIcon(silx.gui.icons.getQIcon("document-save"))
        action.triggered.connect(self.__saveAsCsv)
        action.setToolTip("Save 1D integration as CSV file")
        self.__saveResult1dAction = action
        ownToolBar.addAction(action)

        return plot1d, plot2d

    def __plot2dContextMenu(self, pos):
        from silx.gui.plot.actions.control import ZoomBackAction
        zoomBackAction = ZoomBackAction(plot=self.__plot2d, parent=self.__plot2d)

        menu = qt.QMenu(self)
        maskPixelAction = qt.QAction(menu)
        maskPixelAction.setText("Mark this pixel coord")
        maskPixelAction.triggered.connect(functools.partial(self.__createPixelMarker, pos))
        maskGeometryAction = qt.QAction(menu)
        maskGeometryAction.setText(u"Mark this χ/2θ coord")
        maskGeometryAction.triggered.connect(functools.partial(self.__createGeometryMarker, pos))

        maskPixelAction.setEnabled(self.__geometry is not None)
        maskGeometryAction.setEnabled(self.__geometry is not None)

        menu.addAction(zoomBackAction)
        menu.addSeparator()
        menu.addAction(maskPixelAction)
        menu.addAction(maskGeometryAction)

        handle = self.__plot2d.getWidgetHandle()
        menu.exec_(handle.mapToGlobal(pos))

    def __findUnusedMarkerName(self):
        markerModel = CalibrationContext.instance().getCalibrationModel().markerModel()
        template = "mark%d"
        markerNames = set([m.name() for m in markerModel])
        for i in range(0, 1000):
            name = template % i
            if name not in markerNames:
                return name
        # Returns something
        return "mark"

    def __createPixelMarker(self, pos):
        pos = self.__plot2d.pixelToData(pos.x(), pos.y())
        chiRad, tthRad = self.dataToChiTth(pos)
        pixel = utils.findPixel(self.__geometry, chiRad, tthRad)
        name = self.__findUnusedMarkerName()
        marker = MarkerModel.PixelMarker(name, pixel[1], pixel[0])
        markerModel = CalibrationContext.instance().getCalibrationModel().markerModel()
        markerModel.add(marker)

    def __createGeometryMarker(self, pos):
        pos = self.__plot2d.pixelToData(pos.x(), pos.y())
        chiRad, tthRad = self.dataToChiTth(pos)
        name = self.__findUnusedMarkerName()
        marker = MarkerModel.PhysicalMarker(name, chiRad, tthRad)
        markerModel = CalibrationContext.instance().getCalibrationModel().markerModel()
        markerModel.add(marker)

    def __clearRings(self):
        """Remove of ring item cached on the plots"""
        for items in self.__ringItems.values():
            for item in items:
                self.__plot1d.removeMarker(item.getLegend())
                self.__plot2d.removeMarker(item.getLegend())
        self.__ringItems = {}

    def setIntegrationProcess(self, integrationProcess):
        self.__clearRings()

        self.__availableRingAngles = integrationProcess.ringAngles()
        self.__updateRings()

        # FIXME set axes units
        result1d = integrationProcess.result1d()
        self.__plot1d.addHistogram(
            legend="result1d",
            align="right",
            edges=result1d.radial,
            color="blue",
            histogram=result1d.intensity)

        self.__setResult(result1d)

        # Assume that axes are linear
        result2d = integrationProcess.result2d()
        origin = (result2d.radial[0], result2d.azimuthal[0])
        scaleX = (result2d.radial[-1] - result2d.radial[0]) / result2d.intensity.shape[1]
        scaleY = (result2d.azimuthal[-1] - result2d.azimuthal[0]) / result2d.intensity.shape[0]
        colormap = self.getDefaultColormap()
        self.__plot2d.addImage(
            legend="result2d",
            data=result2d.intensity,
            origin=origin,
            scale=(scaleX, scaleY),
            colormap=colormap)

        self.__radialUnit = integrationProcess.radialUnit()
        self.__wavelength = integrationProcess.wavelength()
        self.__directDist = integrationProcess.directDist()
        self.__geometry = integrationProcess.geometry()
        self.__markerManager.updateProjection(self.__geometry,
                                              self.__radialUnit,
                                              self.__wavelength,
                                              self.__directDist)

    def __setResult(self, result1d):
        self.__result1d = result1d
        self.__saveResult1dAction.setEnabled(result1d is not None)

    def __saveAsCsv(self):
        if self.__result1d is None:
            return
        dialog = createSaveDialog(self, "Save 1D integration as CSV file", csv=True)
        result = dialog.exec_()
        if not result:
            return
        filename = dialog.selectedFiles()[0]
        # TODO: it would be good to store the units
        silx.io.save1D(filename,
                       x=self.__result1d.radial,
                       y=self.__result1d.intensity,
                       xlabel="radial",
                       ylabels=["intensity"],
                       filetype="csv",
                       autoheader=True)

    def setProcessing(self):
        self.__setResult(None)
        self.__processing1d = utils.createProcessingWidgetOverlay(self.__plot1d)
        self.__processing2d = utils.createProcessingWidgetOverlay(self.__plot2d)

    def unsetProcessing(self):
        if self.__processing1d is not None:
            self.__processing1d.deleteLater()
            self.__processing1d = None
        if self.__processing2d is not None:
            self.__processing2d.deleteLater()
            self.__processing2d = None


class IntegrationTask(AbstractCalibrationTask):

    def __init__(self):
        super(IntegrationTask, self).__init__()
        qt.loadUi(pyFAI.utils.get_ui_file("calibration-result.ui"), self)
        self.initNextStep()

        self.__integrationUpToDate = True

        self._radialUnit.setUnits(pyFAI.units.RADIAL_UNITS.values())
        self.__polarizationModel = None
        self._polarizationFactorCheck.clicked[bool].connect(self.__polarizationFactorChecked)
        self.widgetShow.connect(self.__widgetShow)

        self._integrateButton.beforeExecuting.connect(self.__integrate)
        self._integrateButton.setDisabledWhenWaiting(True)
        self._integrateButton.finished.connect(self.__integratingFinished)

        self._savePoniButton.clicked.connect(self.__saveAsPoni)
        self._saveJsonButton.clicked.connect(self.__saveAsJson)

    def aboutToClose(self):
        self._plot.aboutToClose()

    def __polarizationFactorChecked(self, checked):
        self.__polarizationModel.setEnabled(checked)
        self._polarizationFactor.setEnabled(checked)

    def __polarizationModelChanged(self):
        old = self._polarizationFactorCheck.blockSignals(True)
        isEnabled = self.__polarizationModel.isEnabled()
        self._polarizationFactorCheck.setChecked(isEnabled)
        self._polarizationFactor.setEnabled(isEnabled)
        self._polarizationFactorCheck.blockSignals(old)

    def __invalidateIntegration(self):
        if self.isVisible():
            if not self._integrateButton.isWaiting():
                self._integrateButton.executeCallable()
            else:
                # integration is processing
                # but data are already outdated
                self.__integrationUpToDate = False
        else:
            # We can process data later
            self.__integrationUpToDate = False

    def __widgetShow(self):
        if not self.__integrationUpToDate:
            self._integrateButton.executeCallable()

    def __integrate(self):
        self.__integrationProcess = IntegrationProcess(self.model())
        if not self.__integrationProcess.isValid():
            self.__integrationProcess = None
            return
        self.__updateGUIWhileIntegrating()
        self._integrateButton.setCallable(self.__integrationProcess.run)
        self.__integrationUpToDate = True

    def __integratingFinished(self):
        self._plot.unsetProcessing()

        self.__updateGUIWithIntegrationResult(self.__integrationProcess)
        self.__integrationProcess = None
        if not self.__integrationUpToDate:
            # Maybe it was invalidated while priocessing
            self._integrateButton.executeCallable()

    def __updateGUIWhileIntegrating(self):
        self._plot.setProcessing()

    def __updateGUIWithIntegrationResult(self, integrationProcess):
        self._plot.setIntegrationProcess(integrationProcess)

    def _updateModel(self, model):
        experimentSettings = model.experimentSettingsModel()
        integrationSettings = model.integrationSettingsModel()
        self.__polarizationModel = EnablableDataModel(self, experimentSettings.polarizationFactor())
        if self.__polarizationModel.value() is None:
            self.__polarizationModel.setValue(0.9)
        # connect widgets
        self.__polarizationModelChanged()
        self._polarizationFactor.setModel(self.__polarizationModel)
        self._radialUnit.setModel(integrationSettings.radialUnit())
        # connect model
        self.__polarizationModel.changed.connect(self.__polarizationModelChanged)
        experimentSettings.mask().changed.connect(self.__invalidateIntegration)
        experimentSettings.polarizationFactor().changed.connect(self.__invalidateIntegration)
        model.fittedGeometry().changed.connect(self.__invalidateIntegration)
        integrationSettings.radialUnit().changed.connect(self.__invalidateIntegration)

    def __saveAsPoni(self):
        # FIXME test the validity of the geometry before opening the dialog
        dialog = createSaveDialog(self, "Save as PONI file", poni=True)
        result = dialog.exec_()
        if not result:
            return
        filename = dialog.selectedFiles()[0]

        pyfaiGeometry = pyFAI.geometry.Geometry()

        geometry = self.model().fittedGeometry()
        pyfaiGeometry.dist = geometry.distance().value()
        pyfaiGeometry.poni1 = geometry.poni1().value()
        pyfaiGeometry.poni2 = geometry.poni2().value()
        pyfaiGeometry.rot1 = geometry.rotation1().value()
        pyfaiGeometry.rot2 = geometry.rotation2().value()
        pyfaiGeometry.rot3 = geometry.rotation3().value()
        pyfaiGeometry.wavelength = geometry.wavelength().value()

        experimentSettingsModel = self.model().experimentSettingsModel()
        detector = experimentSettingsModel.detector()
        pyfaiGeometry.detector = detector

        pyfaiGeometry.save(filename)

    def __saveAsJson(self):
        pass
