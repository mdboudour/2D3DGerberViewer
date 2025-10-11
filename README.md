Install necessary libraries 
import sys
import os
import re
import random
import math

from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPainterPath, QTransform,QFont,
    QBrush, QPainterPathStroker
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QGraphicsScene,
    QGraphicsView, QGraphicsEllipseItem, QGraphicsRectItem,
    QGraphicsPathItem, QPushButton, QVBoxLayout, QWidget, QListWidget,QGraphicsTextItem,
    QListWidgetItem, QColorDialog, QDockWidget, QHBoxLayout,QComboBox,QDialog,QAction,QGraphicsLineItem,
    QMenu, QInputDialog, QLabel, QGroupBox, QFormLayout, QMessageBox
)
import json

from pyvistaqt import QtInteractor
