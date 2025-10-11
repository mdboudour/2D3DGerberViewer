#!/usr/bin/env python3
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


# ============ 3D IMPORTS ============
import numpy as np
import trimesh
from shapely.geometry import Polygon, Point, LinearRing, MultiPolygon
from shapely.ops import unary_union
import pyvista as pv


class GerberGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene)
        if scene.sceneRect().width() < 100: # Check if current rect is too small
            scene.setSceneRect(QRectF(-1000, -1000, 2000, 2000))
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
       
        self.zoom_factor = 1.15
        self.parent = parent
        self.setMouseTracking(True)

        # --- Grid properties ---
        self.grid_visible = False
        self.grid_spacing = 10.0  # 10 mm spacing
        self.grid_items = []



        
        # 1. ENFORCE LARGE SCENE RECT FOR FREE PANNING
        # This allows infinite movement without losing the ability to add items.
        if scene.sceneRect().width() < 100:
            scene.setSceneRect(QRectF(-1000, -1000, 2000, 2000))
            
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.zoom_factor = 1.15
        self.parent = parent
        self.setMouseTracking(True)

        # --- Grid properties ---
        self.grid_visible = False
        self.grid_spacing = 10.0  # 10 mm spacing
        self.grid_items = []

        # --- Measurement tool ---
        self.measure_mode = False
        self.measure_start = None
        self.temp_line = None
        self.crosshair = None   # NEW: crosshair item
        

    def draw_grid(self):
        """Draws the grid lines, coordinate labels, and the main X-Y axes,
           based on the CURRENTLY VISIBLE AREA (viewport)."""
        self.clear_grid()
        if not self.grid_visible:
            return

        # ----------------------------------------------------
        # 1. CALCULATE BOUNDS FROM VISIBLE AREA
        # ----------------------------------------------------
        
        # Get the rectangle of the viewport mapped to scene coordinates
        visible_rect_poly = self.mapToScene(self.viewport().rect())
        visible_rect = visible_rect_poly.boundingRect()

        grid_spacing = self.grid_spacing
        label_color = Qt.lightGray
        label_font = QFont("Arial", 1)
        grid_pen = QPen(Qt.gray, 0, Qt.DotLine)
        axis_pen = QPen(Qt.darkGray, 0.5, Qt.SolidLine)
        label_offset = 1.5
        
        # Snap the visible limits to the nearest grid line multiple
        x_min = int(visible_rect.left() / grid_spacing) * grid_spacing
        x_max = int(visible_rect.right() / grid_spacing) * grid_spacing
        y_min = int(visible_rect.top() / grid_spacing) * grid_spacing
        y_max = int(visible_rect.bottom() / grid_spacing) * grid_spacing
        
        # Define the full extent for drawing axes/lines (use visible_rect)
        scene_left = visible_rect.left()
        scene_right = visible_rect.right()
        scene_top = visible_rect.top()
        scene_bottom = visible_rect.bottom()

        # ----------------------------------------------------
        # 2. DRAW MAIN X-Y AXES (at x=0 and y=0)
        # ----------------------------------------------------
        # The axes should stretch across the visible area if 0,0 is in view
        
        # Y-Axis (Vertical line at x=0, only if x=0 is visible)
        if scene_left <= 0 <= scene_right:
            y_axis = QGraphicsLineItem(0, scene_top, 0, scene_bottom)
            y_axis.setPen(axis_pen)
            y_axis.setZValue(-0.5)
            self.scene().addItem(y_axis)
            self.grid_items.append(y_axis)
        
        # X-Axis (Horizontal line at y=0, only if y=0 is visible)
        if scene_top <= 0 <= scene_bottom:
            x_axis = QGraphicsLineItem(scene_left, 0, scene_right, 0)
            x_axis.setPen(axis_pen)
            x_axis.setZValue(-0.5)
            self.scene().addItem(x_axis)
            self.grid_items.append(x_axis)

        # ----------------------------------------------------
        # 3. DRAW GRID LINES AND LABELS
        # ----------------------------------------------------
        
        # Vertical lines and X-axis labels
        x = x_min
        while x <= x_max + grid_spacing/2:
            # Draw line (if not 0)
            if abs(x) > 0.001: 
                line = QGraphicsLineItem(x, scene_top, x, scene_bottom)
                line.setPen(grid_pen)
                line.setZValue(-1)
                self.scene().addItem(line)
                self.grid_items.append(line)
            
            # Draw X-axis Label (only every 2nd line or at 0)
            if abs(round(x)) % (grid_spacing * 2) == 0 or abs(round(x)) < grid_spacing:
                text_item = QGraphicsTextItem(f"{x:.0f}")
                text_item.setDefaultTextColor(label_color)
                text_item.setFont(label_font)
                
                # Position at the visible bottom edge
                text_x = x - text_item.boundingRect().width() / 2
                text_y = scene_bottom + label_offset
                
                text_item.setPos(text_x, text_y)
                text_item.setZValue(0)
                self.scene().addItem(text_item)
                self.grid_items.append(text_item)
            
            x += grid_spacing
            
        # Horizontal lines and Y-axis labels
        y = y_min
        while y <= y_max + grid_spacing/2:
            # Draw line (if not 0)
            if abs(y) > 0.001: 
                line = QGraphicsLineItem(scene_left, y, scene_right, y)
                line.setPen(grid_pen)
                line.setZValue(-1)
                self.scene().addItem(line)
                self.grid_items.append(line)
            
            # Draw Y-axis Label
            if abs(round(y)) % (grid_spacing * 2) == 0 or abs(round(y)) < grid_spacing:
                y_value = -y # Display conventional Y (positive up)
                text_item = QGraphicsTextItem(f"{y_value:.0f}") 
                text_item.setDefaultTextColor(label_color)
                text_item.setFont(label_font)
                
                # Position at the visible left edge
                text_x = scene_left - text_item.boundingRect().width() - label_offset
                text_y = y - text_item.boundingRect().height() / 2
                
                if abs(y) < 0.001:
                    text_y -= 0.5 
                    
                text_item.setPos(text_x, text_y)
                text_item.setZValue(0)
                self.scene().addItem(text_item)
                self.grid_items.append(text_item)

            y += grid_spacing

    # --- Event Handlers to Redraw Grid ---

    def resizeEvent(self, event):
        """Redraw grid when the view is resized."""
        super().resizeEvent(event)
        self.draw_grid()

    def wheelEvent(self, event):
        """Redraw grid after zoom."""
        if event.angleDelta().y() > 0:
            self.scale(self.zoom_factor, self.zoom_factor)
        else:
            self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)
        super().wheelEvent(event)
        self.draw_grid()
        
    def mouseReleaseEvent(self, event):
        """Redraw grid after panning is complete (released mouse button)."""
        super().mouseReleaseEvent(event)
        # Only redraw if in pan mode (ScrollHandDrag)
        if self.dragMode() == QGraphicsView.ScrollHandDrag and event.button() == Qt.LeftButton:
            self.draw_grid()
    # ----------------------------------------------------------------------
    # --- Grid/Scene Functions ---
    # ----------------------------------------------------------------------
    
    def toggle_grid(self):
        self.grid_visible = not self.grid_visible
        if self.grid_visible:
            self.draw_grid()
        else:
            self.clear_grid()

 
    def clear_grid(self):
        for item in self.grid_items:
            self.scene().removeItem(item)
        self.grid_items.clear()
        
    # --- NEW FUNCTION: Change background color ---
    def change_scene_background(self):
        """Opens a color dialog and sets the scene's background color."""
        # Get the current background color as the initial selection
        current_color = self.scene().backgroundBrush().color()
        
        # Open the color dialog
        color = QColorDialog.getColor(current_color, self, "Select Scene Background Color")
        
        if color.isValid():
            # Set the new background brush (color)
            self.scene().setBackgroundBrush(color)

    # ----------------------------------------------------------------------
    # --- Context menu ---
    # ----------------------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        # Measure distance action
        measure_action = QAction("Mesure distance", menu)
        measure_action.triggered.connect(lambda: self.start_measure(self.mapToScene(event.pos())))
        menu.addAction(measure_action)
        
        menu.addSeparator()

        # Grid visibility action
        grid_action = QAction("Show Grid (10 mm)", menu)
        grid_action.setCheckable(True)
        grid_action.setChecked(self.grid_visible)
        grid_action.triggered.connect(self.toggle_grid)
        menu.addAction(grid_action)
        
        # --- NEW ACTION: Change Scene Background Color ---
        background_action = QAction("Change Background Color", menu)
        background_action.triggered.connect(self.change_scene_background)
        menu.addAction(background_action)
        
        menu.exec(event.globalPos())


    # -------------------------
    # Crosshair helper functions
    # -------------------------
    def create_crosshair(self, pos):
        """Create a crosshair centered at pos."""
        size = 10  # half length of crosshair arms
        pen = QPen(Qt.red, 0.1, Qt.SolidLine)

        # Horizontal + vertical lines grouped together
        line1 = QGraphicsLineItem(pos.x() - size, pos.y(), pos.x() + size, pos.y())
        line2 = QGraphicsLineItem(pos.x(), pos.y() - size, pos.x(), pos.y() + size)
        line1.setPen(pen)
        line2.setPen(pen)

        # Group them so we can move as one
        group = self.scene().createItemGroup([line1, line2])
        group.setZValue(2)  # above grid
        return group

    def update_crosshair(self, pos):
        """Move crosshair to pos."""
        if self.crosshair:
            self.scene().removeItem(self.crosshair)
            self.crosshair = None
        self.crosshair = self.create_crosshair(pos)
        self.scene().addItem(self.crosshair)

    def clear_crosshair(self):
        if self.crosshair:
            self.scene().removeItem(self.crosshair)
            self.crosshair = None

    # -------------------------
    # Measurement functions
    # -------------------------
    def start_measure(self, start_pos):
        self.measure_mode = True
        self.measure_start = None
        if self.temp_line:
            self.scene().removeItem(self.temp_line)
            self.temp_line = None
        self.clear_crosshair()
        print("Measure mode activated. Click start and end points.")

    def finish_measure(self, end_pos):
        dist = ((end_pos.x() - self.measure_start.x())**2 + 
                (end_pos.y() - self.measure_start.y())**2)**0.5

        if self.temp_line:
            self.scene().removeItem(self.temp_line)
            self.temp_line = None
        self.clear_crosshair()

        if self.parent and hasattr(self.parent, 'dist_label'):
            self.parent.dist_label.setText(f"Distance: {dist:.3f} mm")

        self.measure_start = None
        self.measure_mode = False

    # -------------------------
    # Mouse events
    # -------------------------
    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        if self.measure_mode and event.button() == Qt.LeftButton:
            if self.measure_start is None:
                # First click → start point
                self.measure_start = scene_pos
                print(f"Start point: {scene_pos}")
            else:
                # Second click → finish
                self.finish_measure(scene_pos)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # Update coordinates in status bar
        if self.parent and hasattr(self.parent, 'coord_label'):
            self.parent.coord_label.setText(f"X={scene_pos.x():.3f}, Y={scene_pos.y():.3f}")

        # Update crosshair
        if self.measure_mode:
            self.update_crosshair(scene_pos)

        # Draw temporary measure line
        if self.measure_mode and self.measure_start:
            if self.temp_line:
                self.scene().removeItem(self.temp_line)
                self.temp_line = None
            self.temp_line = QGraphicsLineItem(
                self.measure_start.x(), self.measure_start.y(),
                scene_pos.x(), scene_pos.y()
            )
            pen = QPen(Qt.white, 0.1, Qt.DashLine)
            self.temp_line.setPen(pen)
            self.temp_line.setZValue(1)
            self.scene().addItem(self.temp_line)

            dist = ((scene_pos.x() - self.measure_start.x())**2 +
                    (scene_pos.y() - self.measure_start.y())**2)**0.5
            if self.parent and hasattr(self.parent, 'dist_label'):
                self.parent.dist_label.setText(f"Distance: {dist:.3f} mm")

        super().mouseMoveEvent(event)
        


    # --- Zoom (Unchanged) ---
    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale(self.zoom_factor, self.zoom_factor)
        else:
            self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)

    # --- Double click (Unchanged) ---
    def mouseDoubleClickEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        items = self.scene().items(scene_pos)
        if items and self.parent and hasattr(self.parent, 'change_layer_color'):
            clicked_item = items[0]
            self.parent.change_layer_color(clicked_item)
        super().mouseDoubleClickEvent(event)
        
# ---------- IPC-D-356 Parser ----------
class IPCParser:
    def __init__(self, filename):
        self.filename = filename

    def parse(self):
        nets = {}
        coord_regex = re.compile(r'X([+-]?\d+)Y([+-]?\d+)')
        with open(self.filename, "r") as f:
            for line in f:
                if line.startswith("P ") or line.startswith("999"):
                    continue
                parts = line.split()
                if not parts:
                    continue
                net_name = parts[0]
                match = coord_regex.search(line)
                if match:
                    try:
                        x = float(match.group(1)) / 254
                        y = float(match.group(2)) / 254  
                        if net_name not in nets:
                            nets[net_name] = []
                        nets[net_name].append((x, y))
                    except Exception:
                        pass
        return nets

class GerberViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gerber Viewer, By Mohamed Boudour, Eng")
        self.resize(1200, 900)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor(0, 0, 0))
        self.view = GerberGraphicsView(self.scene, parent=self)

        # Buttons
        open_btn = QPushButton("Open Gerber")
        drill_btn = QPushButton("Load Drill")
        outline_btn = QPushButton("Load Board Outline")
        nets_btn = QPushButton("Load D356 Nets")
        view3d_btn = QPushButton("3D View")
        save_project_btn = QPushButton("Save Project")
        open_project_btn = QPushButton("Open Project")
        new_btn = QPushButton("New Project")
  
          # Deactivate them by default
        save_project_btn.setDisabled(True)
        open_project_btn.setDisabled(True)
        new_btn.setDisabled(True)

        open_btn.clicked.connect(self.open_files)
        drill_btn.clicked.connect(self.open_drill_file)
        outline_btn.clicked.connect(self.load_board_outline)
        #nets_btn.clicked.connect(self.load_nets_file)
        nets_btn.clicked.connect(self.load_d356)
        view3d_btn.clicked.connect(self.export_to_3d)
        save_project_btn.clicked.connect(self.save_project)
        open_project_btn.clicked.connect(self.open_project)
        new_btn.clicked.connect(self.new_project)


        top_layout = QHBoxLayout()
        top_layout.addWidget(open_btn)
        top_layout.addWidget(drill_btn)
        top_layout.addWidget(outline_btn)
        top_layout.addWidget(nets_btn)
        top_layout.addWidget(view3d_btn)
        top_layout.addWidget(save_project_btn)
        top_layout.addWidget(open_project_btn)
        top_layout.addWidget(new_btn)
        top_layout.addStretch()

        main_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.view)
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # Dock
        dock_widget = QWidget()
        dock_layout = QVBoxLayout()
        self.layer_list = QListWidget()
        self.layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self.show_layer_context_menu)
        self.layer_list.setDragDropMode(QListWidget.InternalMove)
        self.layer_list.model().rowsMoved.connect(self.reorder_layers)
        self.layer_list.itemDoubleClicked.connect(self.change_layer_color)
        self.layer_list.itemChanged.connect(self.toggle_layer)

        layer_group = QGroupBox("Layers")
        layer_group.setLayout(QVBoxLayout())
        layer_group.layout().addWidget(self.layer_list)


        # Nets List
        self.nets_list = QListWidget()
        nets_group = QGroupBox("Nets")
        nets_layout = QVBoxLayout()
        nets_layout.addWidget(self.nets_list)
        nets_group.setLayout(nets_layout)
        self.nets_list.itemClicked.connect(self.highlight_net)
        
        dock_layout.addWidget(layer_group)
        dock_layout.addWidget(nets_group)
        dock_widget.setLayout(dock_layout)
        
        dock = QDockWidget("Layers", self)
        dock.setWidget(dock_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # State
        self.layers = {}
        #self.nets = []
        self.nets = {}
        self.highlight_items = []
        
        self.board_outline_polygons = []
        self.loaded_layers = []  # stores (name, path, items, brush)

        self.dec_d = 5
        self.aperture_macros = {}
        self.current_pos = QPointF(0, 0)
        self.current_aperture = None
        self.mirrored = False
        self.rotation_angle = 0
        self.units = "mm"

        # Origin cross
        origin_size = 20
        pen = QPen(QColor("red"))
        #self.scene.addLine(-origin_size, 0, origin_size, 0, pen)
        #self.scene.addLine(0, -origin_size, 0, origin_size, pen)


        self.unit_label = QLabel("unit: mm\t")
        self.statusBar().addPermanentWidget(self.unit_label)
        
        self.coord_label = QLabel("X=0.000, Y=0.000")
        self.statusBar().addPermanentWidget(self.coord_label)
        
        self.dist_label = QLabel("")  # New label for distance
        self.statusBar().addPermanentWidget(self.dist_label)





    def new_project(self):
        # Clear the QGraphicsScene
        self.scene.clear()
        
        # Clear the QListWidget
        self.layer_list.clear()
        
        # Clear internal dictionaries
        self.layers.clear()
        
        # Clear the class-level loaded layers
        self.loaded_layers = []
        
        # Clear board outline polygons if used
        if hasattr(self, "board_outline_polygons"):
            self.board_outline_polygons = []

        # Optionally reset the view
        self.view.resetTransform()
        self.view.setSceneRect(0, 0, 1000, 1000)  # or appropriate default

        print("New project initialized")


   # -----------------------------
    # Save Project Button Function
    # -----------------------------
    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "BM Project (*.bm)"
        )
        if not path:
            return

        # Gather layers info in list order from layer_list
        project_layers = []
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            name = item.data(Qt.UserRole)
            # Find layer in loaded_layers to save path, brush, and outline info
            for layer in getattr(self, "loaded_layers", []):
                # Unpack loaded_layer, handle outline flag
                if len(layer) == 5:
                    lname, lpath, items, brush, is_outline = layer
                else:
                    lname, lpath, items, brush = layer
                    is_outline = False

                if lname == name:
                    color = brush.color()
                    project_layers.append({
                        "name": lname,
                        "path": lpath,
                        "color": [color.red(), color.green(), color.blue()],
                        "is_outline": is_outline
                    })
                    break

        # Save as JSON
        with open(path, "w") as f:
            json.dump(project_layers, f, indent=2)

        print(f"Project saved to {path}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "BM Project (*.bm)"
        )
        if not path:
            return

        with open(path, "r") as f:
            project_layers = json.load(f)

        # Clear current scene, list, layers, loaded_layers, and board outline
        self.scene.clear()
        self.layer_list.clear()
        self.layers.clear()
        self.loaded_layers = []
        self.board_outline_polygons = []

        for layer_info in project_layers:
            filepath = layer_info.get("path", "")
            if not filepath or not os.path.exists(filepath):
                print(f"Skipping missing file: {filepath}")
                continue

            name = os.path.basename(filepath)
            lname = name.lower()

            # Decide parser based on extension
            if lname.endswith((".drl", ".txt", ".xln")) or "drill" in lname:
                items = self.parse_drill(filepath)
            else:
                items = self.parse_gerber(filepath)

            if not items:
                continue

            # Use saved color if available
            color_list = layer_info.get("color")
            if color_list and len(color_list) == 3:
                color = QColor(*color_list)
            else:
                if lname.endswith(".gtl"):
                    color = QColor(255, 0, 0)
                elif lname.endswith(".gbl"):
                    color = QColor(0, 0, 255)
                else:
                    color = QColor.fromHsl(random.randint(0, 359), 255, 200)

            brush = QBrush(color)

            # Check if this layer is a board outline
            is_outline = layer_info.get("is_outline", False)

            # Add to class-level loaded_layers
            self.loaded_layers.append((name, filepath, items, brush, is_outline))


            # Add items to scene
            scene_items = []
            for it in items:
                if isinstance(it, QPainterPath):
                    it.setFillRule(Qt.WindingFill)
                    item = self.scene.addPath(it, QPen(Qt.NoPen), brush)
                else:
                    try:
                        it.setPen(QPen(Qt.NoPen))
                        it.setBrush(brush)
                    except:
                        pass
                    self.scene.addItem(it)
                    item = it
                scene_items.append(item)
            # If outline, rebuild board_outline_polygons for 3D mode
            if is_outline:
                self.board_outline_polygons = self._extract_polygons_from_items(items, is_outline=True)

            group = self.scene.createItemGroup(scene_items)
            self.layers[name] = {
                "group": group,
                "items": scene_items,
                "brush": brush,
                "path": filepath,
                "is_outline": is_outline
            }

            # Add to QListWidget
            lw_name = name + " [OUTLINE]" if is_outline else name
            lw = QListWidgetItem(lw_name)
            lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
            lw.setCheckState(Qt.Checked)
            lw.setData(Qt.UserRole, name)
            self.layer_list.addItem(lw)

        # Fit view
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        print(f"Project {path} loaded")
        

    def reorder_layers(self, parent, start, end, destination, row):
        """
        Called after the user moves layers in the QListWidget.
        Updates the Z-order of the corresponding QGraphicsItem groups in the scene.
        """
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            name = item.data(Qt.UserRole)
            layer = self.layers.get(name)
            if layer:
                # Set Z-value based on the order in the list
                layer["group"].setZValue(i)


    def show_layer_context_menu(self, pos):
        item = self.layer_list.itemAt(pos)
        if not item:
            return

        name = item.data(Qt.UserRole)
        layer = self.layers.get(name)
        if not layer:
            return

        menu = QMenu()

        # Add actions
        change_color_action = menu.addAction("Change Color")
        hide_layer_action = None
        if layer.get("group") and layer["group"].isVisible():
            hide_layer_action = menu.addAction("Hide Layer")
        else:
            hide_layer_action = menu.addAction("Show Layer")
        delete_layer_action = menu.addAction("Delete Layer")

        action = menu.exec_(self.layer_list.mapToGlobal(pos))

        if action == change_color_action:
            self.change_layer_color(item)
        elif action == delete_layer_action:
            self.delete_layer(item)
        elif action == hide_layer_action:
            self.toggle_layer_visibility(item)


    def toggle_layer_visibility(self, item):
        name = item.data(Qt.UserRole)
        layer = self.layers.get(name)
        if not layer:
            return

        if "group" in layer:
            is_visible = layer["group"].isVisible()
            layer["group"].setVisible(not is_visible)

            # Optionally, update the QListWidget item text or color to indicate hidden state
            font = item.font()
           # font.setStrikeOut(not is_visible)  # strikethrough text when hidden
            item.setFont(font)




    def delete_layer(self, item):
        name = item.data(Qt.UserRole)
        layer = self.layers.get(name)
        if not layer:
            return

        # Remove graphics from scene
        if "group" in layer:
            self.scene.removeItem(layer["group"])

        # Remove from dictionary
        if name in self.layers:
            del self.layers[name]

        # Remove from QListWidget
        row = self.layer_list.row(item)
        self.layer_list.takeItem(row)



    def change_layer_color(self, item):
        name = item.data(Qt.UserRole)
        layer = self.layers.get(name)
        if not layer:
            return
        current_color = layer["brush"].color() if "brush" in layer else QColor(200, 100, 50)
        color = QColorDialog.getColor(current_color, self, f"Select Color for {name}")
        if color.isValid():
            # Update brush
            layer["brush"] = QBrush(color)
            # Update existing scene items
            for it in layer["items"]:
                if isinstance(it, (QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem)):
                    it.setBrush(layer["brush"])
            # For 3D export, the next export will use the new color


    def load_board_outline2(self):
        
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Board Outline (Gerber Mechanical/Edge Cuts)",
            "",
            "Gerber Files (*.gbr *.gm* *.gml *.oln *.out);;All Files (*)"
        )

        if not path:
            return

        name = os.path.basename(path)
        items = self.parse_gerber(path)
        if not items:
            QMessageBox.warning(self, "Error", "No data in outline file!")
            return

        # Extract polygons from items for internal use
        self.board_outline_polygons = self._extract_polygons_from_items(items, is_outline=True)
        
        scene_items = []
        pcb_fill_color = QColor(0, 150, 0) # Default green color
        
        # --- START: Logic to create the green polygonal fill ---

        board_path = QPainterPath()
        
        if self.board_outline_polygons:
            # Combine all outline shapes into a single QPainterPath for the fill
            for poly_or_path in self.board_outline_polygons:
                try:
                    if isinstance(poly_or_path, QPainterPath):
                        if not poly_or_path.isEmpty():
                            board_path.addPath(poly_or_path)
                        
                    elif isinstance(poly_or_path, QPolygonF):
                        if not poly_or_path.isEmpty():
                            # Use QPainterPath.addPolygon to add the polygon
                            board_path.addPolygon(poly_or_path)

                    elif hasattr(poly_or_path, 'path') and isinstance(poly_or_path.path(), QPainterPath):
                        if not poly_or_path.path().isEmpty():
                            board_path.addPath(poly_or_path.path())
                    
                except Exception as e:
                    print(f"Failed to add outline geometry to fill path: {e}")
                    continue 

        if not board_path.isEmpty():
            # 1. Create the green fill item using the actual board shape path
            pcb_fill_brush = QBrush(pcb_fill_color)
            
            # Use QGraphicsPathItem to draw the complex shape
            pcb_fill_item = QGraphicsPathItem(board_path)
            
            # CRITICAL: If WindingFill fails, try OddEvenFill. 
            # OddEvenFill ignores winding direction and simply alternates fill/no-fill, 
            # which often correctly handles complex, intersecting, or non-directional paths.
            pcb_fill_item.setFillRule(Qt.OddEvenFill)
            # If OddEvenFill doesn't work, revert to WindingFill:
            # pcb_fill_item.setFillRule(Qt.WindingFill) 
            
            pcb_fill_item.setBrush(pcb_fill_brush)
            pcb_fill_item.setPen(QPen(Qt.NoPen)) # No outline for the fill
            
            # Add the green fill to the scene and the list of items
            self.scene.addItem(pcb_fill_item)
            scene_items.append(pcb_fill_item) # This item will be the background

        # --- END: Logic ---

        # Add the actual board outline paths/items on top of the green shape
        brush = QBrush(QColor("white"))  

        for it in items:
            try:
                if isinstance(it, QPainterPath):
                    # Ensure the outline path itself has the same fill rule if it's meant to be an area
                    it.setFillRule(Qt.OddEvenFill if not board_path.isEmpty() else Qt.WindingFill)
                    # Add the path item to the scene with a clear white stroke and NO FILL
                    item = self.scene.addPath(it, QPen(QColor("white"), 0.5), QBrush(Qt.NoBrush))
                    
                else:
                    # Assuming 'it' is already a QGraphicsItem
                    it.setPen(QPen(QColor("white"), 0.5))
                    it.setBrush(QBrush(Qt.NoBrush)) 
                    self.scene.addItem(it)
                    item = it
                    
                scene_items.append(item) 

            except Exception as e:
                print(f"Skipping malformed graphics item during final drawing: {e}")
                continue 

        group = self.scene.createItemGroup(scene_items)
        # Save in layers dict with outline flag
        self.layers[name] = {
            "group": group,
            "items": scene_items,
            "brush": QBrush(pcb_fill_color) if not board_path.isEmpty() else brush, 
            "path": path,
            "is_outline": True
        }

        # Add to class-level loaded_layers for saving project
        if not hasattr(self, "loaded_layers"):
            self.loaded_layers = []
        self.loaded_layers.append((name, path, items, brush, True)) 

        # Add to list widget
        lw = QListWidgetItem(name + " [OUTLINE]")
        lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
        lw.setCheckState(Qt.Checked)
        lw.setData(Qt.UserRole, name)
        self.layer_list.addItem(lw)

        # Fit the view to the bounding rectangle of the newly added items
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

  
    def load_board_outline1(self):
        """
        Loads a Gerber board outline file, calculates its bounding box,
        fills the bounding box with a green background, and then draws the outline paths.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Board Outline (Gerber Mechanical/Edge Cuts)",
            "",
            "Gerber Files (*.gbr *.gm* *.gml *.oln *.out);;All Files (*)"
        )

        if not path:
            return

        name = os.path.basename(path)
        # NOTE: Assuming self.parse_gerber() and self._extract_polygons_from_items() are defined elsewhere
        items = self.parse_gerber(path)
        if not items:
            QMessageBox.warning(self, "Error", "No data in outline file!")
            return

        # Extract polygons from items for internal use
        self.board_outline_polygons = self._extract_polygons_from_items(items, is_outline=True)

        # --- START: New logic to calculate bounds and add green fill ---
        
        # 1. Calculate the bounding rectangle for all geometric items in 'items'
        bounds = QRectF()
        for it in items:
            try:
                # Use boundingRect for QPainterPath and QGraphicsItems
                # If 'it' is a QGraphicsItem, its boundingRect is usually sufficient.
                # If 'it' is a QPainterPath, it has a controlPointRect() or boundingRect()
                current_rect = it.boundingRect() if hasattr(it, 'boundingRect') else it.controlPointRect()
                bounds = bounds.united(current_rect)
            except AttributeError:
                # Skip items that don't have bounding methods
                continue

        scene_items = []

        if not bounds.isEmpty():
            # 2. Create the green rectangular fill item
            # Use a classic PCB green color (e.g., RGB: 0, 150, 0)
            pcb_fill_color = QColor(0, 150, 0)
            pcb_fill_brush = QBrush(pcb_fill_color)
            
            # Create the rectangle item spanning the bounds
            pcb_rect = QGraphicsRectItem(bounds)
            pcb_rect.setBrush(pcb_fill_brush)
            pcb_rect.setPen(QPen(Qt.NoPen)) # No outline for the fill rectangle
            
            # Add the green fill to the scene and the list of items
            self.scene.addItem(pcb_rect)
            scene_items.append(pcb_rect) # This item will be the background (first in list)

        # --- END: New logic ---

        # Add the actual board outline paths/items on top of the green rectangle
        brush = QBrush(QColor("white"))  # Outline/Edge-Cuts usually stand out as white/no fill

        for it in items:
            if isinstance(it, QPainterPath):
                it.setFillRule(Qt.WindingFill)
                # The outline path itself should typically NOT be filled to show the edge
                # or it should be filled with the outline color for proper path representation
                # For a simple outline view, we only want the stroke, so we'll use NoPen for the path itself
                # and let the underlying rect provide the color. 
                # If the Gerber data is a *filled* area, we use the brush. We'll use the 'brush' (white) here 
                # for consistency with the original code, assuming 'items' are paths/areas to be drawn.
                item = self.scene.addPath(it, QPen(Qt.NoPen), brush) 
            else:
                try:
                    # Assuming 'it' is already a QGraphicsItem
                    it.setPen(QPen(Qt.NoPen))
                    it.setBrush(brush) # Set item's fill to white/outline color
                except:
                    pass
                self.scene.addItem(it)
                item = it
                
            scene_items.append(item) # These items draw on top of the green rect

        group = self.scene.createItemGroup(scene_items)
        # Save in layers dict with outline flag
        self.layers[name] = {
            "group": group,
            "items": scene_items,
            # Save the green fill color for the layer, or stick with the outline color if preferred
            "brush": QBrush(pcb_fill_color) if not bounds.isEmpty() else brush, 
            "path": path,
            "is_outline": True
        }

        # Add to class-level loaded_layers for saving project
        if not hasattr(self, "loaded_layers"):
            self.loaded_layers = []
        # Note: Using the original outline brush/color for project saving data consistency
        self.loaded_layers.append((name, path, items, brush, True)) # last True = is_outline

        # Add to list widget
        lw = QListWidgetItem(name + " [OUTLINE]")
        lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
        lw.setCheckState(Qt.Checked)
        lw.setData(Qt.UserRole, name)
        self.layer_list.addItem(lw)

        # Fit the view to the bounding rectangle of the newly added items
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        
    def load_board_outline(self):

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Board Outline (Gerber Mechanical/Edge Cuts)",
            "",
            "Gerber Files (*.gbr *.gm* *.gml *.oln *.out);;All Files (*)"
        )

        if not path:
            return

        name = os.path.basename(path)
        items = self.parse_gerber(path)
        if not items:
            QMessageBox.warning(self, "Error", "No data in outline file!")
            return

        # Extract polygons from items for internal use
        self.board_outline_polygons = self._extract_polygons_from_items(items, is_outline=True)

        # Add to scene
        brush = QBrush(QColor("white"))  # Outline usually white
        scene_items = []
        for it in items:
            if isinstance(it, QPainterPath):
                it.setFillRule(Qt.WindingFill)
                item = self.scene.addPath(it, QPen(Qt.NoPen), brush)
            else:
                try:
                    it.setPen(QPen(Qt.NoPen))
                    it.setBrush(brush)
                except:
                    pass
                self.scene.addItem(it)
                item = it
            scene_items.append(item)

        group = self.scene.createItemGroup(scene_items)
        # Save in layers dict with outline flag
        self.layers[name] = {
            "group": group,
            "items": scene_items,
            "brush": brush,
            "path": path,
            "is_outline": True
        }

        # Add to class-level loaded_layers for saving project
        if not hasattr(self, "loaded_layers"):
            self.loaded_layers = []
        self.loaded_layers.append((name, path, items, brush, True))  # last True = is_outline

        # Add to list widget
        lw = QListWidgetItem(name + " [OUTLINE]")
        lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
        lw.setCheckState(Qt.Checked)
        lw.setData(Qt.UserRole, name)
        self.layer_list.addItem(lw)

        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)


    def _extract_polygons_from_items(self, items, is_outline=False):
        """Convert Qt items (either QPainterPath or QGraphicsItems) to Shapely polygons in scene coords.
        - Handles QPainterPath (pre-scene), QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem.
        - Uses scene coordinates when possible so transforms are respected.
        """
        polys = []

        def coords_close_and_fix(coords):
            if len(coords) < 3:
                return None
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            try:
                poly = Polygon(coords)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_valid and not poly.is_empty and poly.area > 1e-9:
                    return poly
            except Exception as e:
                print(f"coords_close_and_fix error: {e}")
            return None

        for item in items:
            try:
                # QGraphicsEllipseItem (either pre-scene or scene item)
                if isinstance(item, QGraphicsEllipseItem):
                    # If item is in scene, use sceneBoundingRect to respect transforms
                    if item.scene() is not None:
                        rect = item.sceneBoundingRect()
                        cx, cy = rect.center().x(), rect.center().y()
                        rx = rect.width() / 2.0
                        ry = rect.height() / 2.0
                    else:
                        rect = item.rect()
                        cx, cy = rect.center().x(), rect.center().y()
                        rx = rect.width() / 2.0
                        ry = rect.height() / 2.0
                    samples = 24
                    coords = [(cx + rx * math.cos(2 * math.pi * k / samples),
                               cy + ry * math.sin(2 * math.pi * k / samples)) for k in range(samples)]
                    poly = coords_close_and_fix(coords)
                    if poly:
                        polys.append(poly)
                    continue

                # QGraphicsRectItem
                if isinstance(item, QGraphicsRectItem):
                    if item.scene() is not None:
                        rect = item.sceneBoundingRect()
                    else:
                        rect = item.rect()
                    coords = [
                        (rect.left(), rect.top()),
                        (rect.right(), rect.top()),
                        (rect.right(), rect.bottom()),
                        (rect.left(), rect.bottom()),
                        (rect.left(), rect.top())
                    ]
                    poly = coords_close_and_fix(coords)
                    if poly:
                        polys.append(poly)
                    continue

                # QGraphicsPathItem (scene item)
                if isinstance(item, QGraphicsPathItem):
                    path = item.path()
                    subpaths = path.toSubpathPolygons()
                    for sp in subpaths:
                        if len(sp) < 3:
                            continue
                        coords = []
                        for p in sp:
                            # p is in the item's local coordinates: map to scene
                            pt = item.mapToScene(p)
                            coords.append((pt.x(), pt.y()))
                        poly = coords_close_and_fix(coords)
                        if poly:
                            polys.append(poly)
                    continue

                # QPainterPath (pre-scene path returned by parse_gerber)
                if isinstance(item, QPainterPath):
                    subpaths = item.toSubpathPolygons()
                    for sp in subpaths:
                        if len(sp) < 3:
                            continue
                        coords = [(p.x(), p.y()) for p in sp]
                        poly = coords_close_and_fix(coords)
                        if poly:
                            polys.append(poly)
                    continue

                # Fallback: if item has sceneBoundingRect, use that rectangle
                if hasattr(item, "sceneBoundingRect"):
                    rect = item.sceneBoundingRect() if item.scene() is not None else item.boundingRect()
                    coords = [
                        (rect.left(), rect.top()),
                        (rect.right(), rect.top()),
                        (rect.right(), rect.bottom()),
                        (rect.left(), rect.bottom()),
                        (rect.left(), rect.top())
                    ]
                    poly = coords_close_and_fix(coords)
                    if poly:
                        polys.append(poly)
            except Exception as e:
                print(f"_extract_polygons_from_items error for item {type(item)}: {e}")
                continue

        # Try to merge nearby polygons (remove tiny slivers)
        if polys:
            try:
                u = unary_union([p for p in polys if p.is_valid and not p.is_empty])
                if u.is_empty:
                    return []
                if u.geom_type == 'Polygon':
                    return [u]
                elif u.geom_type == 'MultiPolygon':
                    # filter very small pieces
                    parts = [p for p in u.geoms if p.area > 1e-9]
                    return parts if parts else []
            except Exception as e:
                print(f"unary_union error: {e}")
                return polys

        return polys

    # ---------- Utilities ----------
    def highlight_net(self, item):
        net_name = item.text()
        for net_data in self.nets.values():
            for graphic_item in net_data['items']:
                graphic_item.setBrush(QBrush(Qt.green))
                graphic_item.setPen(QPen(Qt.black, 0.1))
        if net_name in self.nets:
            for graphic_item in self.nets[net_name]['items']:
                graphic_item.setBrush(QBrush(Qt.yellow))
                graphic_item.setPen(QPen(Qt.red, 0.3))
                

    def load_d356(self):
        file, _ = QFileDialog.getOpenFileName(None, "Open IPC-D-356 File", "", "D356 Files (*.d356 *.txt)")
        if not file:
            return

        if self.nets:
            for net_data in self.nets.values():
                for graphic_item in net_data['items']:
                    self.scene.removeItem(graphic_item)
        self.nets.clear()
        self.nets_list.clear()
        current_pos = QPointF(0,0)
        parser = IPCParser(file)
        parsed_nets = parser.parse()
        
        if not parsed_nets:
            print("No nets found.")
            return

        for net_name, coords in parsed_nets.items():
            list_item = QListWidgetItem(net_name)
            self.nets_list.addItem(list_item)
            items = []
            
            for (x, y) in coords:
                dot_size = 2.0
                dot = self.scene.addEllipse(
                    self.current_pos.x() + x - dot_size/2,
                    self.current_pos.y() - y - dot_size/2,
                    dot_size, dot_size,
                    QPen(Qt.black, 0.1), QBrush(Qt.green)
                )
                dot.setData(0, net_name)
                dot.setZValue(100)
                items.append(dot)

            self.nets[net_name] = {'items': items, 'coords': coords}

        self.center_board()
        
    def center_board(self):
        rect = self.scene.itemsBoundingRect()
        self.view.centerOn(rect.center())    
    
    def load_nets_file(self):
        
        path, _ = QFileDialog.getOpenFileName(
            self, "Select d356 Net File",
            "", "Net Files (*.txt *.net *.d356);;All Files (*)"
        )
        
        if not path:
            return

        self.nets.clear()
        self.nets_list.clear()
        
        try:
            with open(path, 'r') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue
                    self.nets.append(stripped)
                    item = QListWidgetItem(stripped)
                    self.nets_list.addItem(item)
        except Exception as e:
            print(f"Error loading net file: {e}")
            return

        print(f"Loaded {len(self.nets)} nets from {os.path.basename(path)}")


      
    def export_to_3d(self):
            """
            Generates a 3D PyVista plot of the PCB, including layered copper, mask,
            silkscreen data, and drilled holes (rendered as cylinders).
            """
            # The following imports are assumed to exist in the surrounding class/file scope:
            # import re
            # from PyQt5.QtWidgets import (QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, 
            #                              QLabel, QComboBox, QPushButton)
            # from PyQt5.QtGui import QBrush, QColor
            # import pyvista as pv
            # import trimesh
            # from shapely.ops import unary_union
            # from shapely.geometry import Polygon

            if not self.board_outline_polygons:
                QMessageBox.warning(self, "Missing Outline", "Load a board outline first!")
                return

            # -------------------------
            # Thicknesses
            # -------------------------
            unitFactor = 1
            if self.units == "inch":
                unitFactor = 25.4
                
            BOARD_THICKNESS = 1.6 / unitFactor
            COPPER_THICKNESS = 0.035 / unitFactor
            SILK_THICKNESS = 0.015 / unitFactor
            MASK_THICKNESS = 0.01 / unitFactor
            PASTE_THICKNESS = 0.1 / unitFactor
            EPSILON = 0.001 / unitFactor
            HOLE_HEIGHT = BOARD_THICKNESS + COPPER_THICKNESS + SILK_THICKNESS + MASK_THICKNESS + PASTE_THICKNESS + EPSILON 
            # -------------------------
            # Helper to auto-detect layers
            # -------------------------

            def auto_detect_layer(patterns):
                """
                Try to detect a layer name by matching multiple patterns (extensions or keywords).
                `patterns` can be a list of regex strings.
                """
                for lname in self.layers.keys():
                    for pat in patterns:
                        if re.search(pat, lname, re.IGNORECASE):
                            return lname
                return None
                    # -------------------------
            # Part 1: Layer Selection Dialog
            # -------------------------
            dialog = QDialog(self)
            dialog.setWindowTitle("Select Layers for 3D View")
            layout = QVBoxLayout(dialog)

            def add_layer_selector(label_text, default_layer=None):
                hl = QHBoxLayout()
                lbl = QLabel(label_text)
                combo = QComboBox()
                combo.addItem("(none)")
                for lname in self.layers.keys():
                    combo.addItem(lname)
                if default_layer and default_layer in self.layers:
                    combo.setCurrentText(default_layer)  # pre-select detected layer
                hl.addWidget(lbl)
                hl.addWidget(combo)
                layout.addLayout(hl)
                return combo

            top_copper    = add_layer_selector("Top Copper",
                                                 auto_detect_layer([r"\.gtl$", r"top.*copper", r"top[^a-z0-9]*"]))
            top_silk      = add_layer_selector("Top Silkscreen",
                                                 auto_detect_layer([r"\.gto$", r"top.*silk"]))
            top_mask      = add_layer_selector("Top Mask",
                                                 auto_detect_layer([r"\.gts$", r"top.*mask"]))
            top_paste     = add_layer_selector("Top Paste",
                                                 auto_detect_layer([r"\.gtp$", r"top.*paste"]))

            bottom_copper = add_layer_selector("Bottom Copper",
                                                 auto_detect_layer([r"\.gbl$", r"bottom.*copper", r"bot[^a-z0-9]*"]))
            bottom_silk   = add_layer_selector("Bottom Silkscreen",
                                                 auto_detect_layer([r"\.gbo$", r"bottom.*silk"]))
            bottom_mask   = add_layer_selector("Bottom Mask",
                                                 auto_detect_layer([r"\.gbs$", r"bottom.*mask"]))
            bottom_paste  = add_layer_selector("Bottom Paste",
                                                 auto_detect_layer([r"\.gbp$", r"bottom.*paste"]))

            inner_combos  = [add_layer_selector(f"Inner Layer {i}",
                                                 auto_detect_layer([rf"\.g{i}l$", rf"inner\s*{i}"]))
                                 for i in range(1, 17)]


            # OK / Cancel buttons
            btns = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Cancel")
            btns.addWidget(ok_btn)
            btns.addWidget(cancel_btn)
            layout.addLayout(btns)
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            if dialog.exec_() != QDialog.Accepted:
                return

            chosen_layers = {
                "top": {"copper": top_copper.currentText(), "silk": top_silk.currentText(),
                        "paste": top_paste.currentText(), "mask": top_mask.currentText()},
                "bottom": {"copper": bottom_copper.currentText(), "silk": bottom_silk.currentText(),
                           "paste": bottom_paste.currentText(), "mask": bottom_mask.currentText()},
                "inner": [combo.currentText() for combo in inner_combos if combo.currentText() != "(none)"]
            }

            # -------------------------
            # Part 2: Board Outline
            # -------------------------
            valid_outlines = [p for p in self.board_outline_polygons if p.is_valid and not p.is_empty and p.area > 1e-6]
            if not valid_outlines:
                QMessageBox.critical(self, "Invalid Outline", "No valid board shape found!")
                return

            board_shape = unary_union(valid_outlines)
            if board_shape.geom_type == 'MultiPolygon':
                board_shape = max(board_shape.geoms, key=lambda p: p.area)
            
            # Robust cleanup of the board shape polygon (Buffer(0) removes self-intersections)
            board_shape = board_shape.buffer(0).buffer(0)
            
            if board_shape.is_empty or not board_shape.is_valid:
                QMessageBox.critical(self, "Invalid Outline", "No valid board polygon after cleanup.")
                return

            # -------------------------
            # Part 3: 3D Mesh Generation
            # -------------------------
            plotter = pv.Plotter(window_size=[1200, 800])
            plotter.set_background("black")
            layer_actors = {}

            try:
                # FIX: Extrude the board shape directly to maintain complex outline.
                board_mesh_trimesh = trimesh.creation.extrude_polygon(board_shape, height=BOARD_THICKNESS + EPSILON)
                # Removed: board_mesh_trimesh = board_mesh_trimesh.convex_hull 
                
                board_mesh_pv = pv.wrap(board_mesh_trimesh)
                actor = plotter.add_mesh(board_mesh_pv, color="#006600", name="Board Substrate")
                layer_actors["Board Substrate"] = actor
            except Exception as e:
                QMessageBox.critical(self, "3D Error", f"Board mesh failed:\n{str(e)}")
                return

            # -------------------------
            # Helper to plot a layer
            # -------------------------
            def plot_layer(display_name, gerber_name, z_start, height):
                if gerber_name not in self.layers or gerber_name == "(none)":
                    return
                layer = self.layers[gerber_name]
                if not layer["group"].isVisible():
                    return

                brush = layer.get("brush", QBrush(QColor(200, 100, 50)))
                color = brush.color()
                rgba_color = [color.redF(), color.greenF(), color.blueF(), 1.0]

                polys = self._extract_polygons_from_items(layer["items"])
                layer_meshes = []
                for poly in polys:
                    if poly.is_empty or not poly.is_valid:
                        continue
                    try:
                        # Apply a robust cleanup (buffer(0)) to each feature polygon before extrusion
                        cleaned_poly = poly.buffer(0) 
                        mesh = trimesh.creation.extrude_polygon(cleaned_poly, height=max(height, EPSILON))
                        mesh.apply_translation([0, 0, z_start])
                        layer_meshes.append(mesh)
                    except Exception as e:
                        print(f"Extrusion error for {display_name}: {e}")

                if not layer_meshes:
                    return

                # Note: For copper/mask layers, you might consider using trimesh.boolean.union() 
                # instead of concatenate to reduce the final mesh size and combine touching features, 
                # but concatenate is safer for layers with complex non-touching features.
                combined_mesh = trimesh.util.concatenate(layer_meshes)
                pv_mesh = pv.wrap(combined_mesh)
                actor = plotter.add_mesh(pv_mesh, color=rgba_color[:3], opacity=rgba_color[3], name=display_name)
                layer_actors[display_name] = actor

            # -------------------------
            # Layer Stacking
            # -------------------------
            # Top layers
            z_top = 0
            z_top -= COPPER_THICKNESS
            plot_layer("Top Copper", chosen_layers["top"]["copper"], z_top , COPPER_THICKNESS)
            z_top -= MASK_THICKNESS
            plot_layer("Top Mask", chosen_layers["top"]["mask"], z_top , MASK_THICKNESS)
            z_top -= SILK_THICKNESS
            plot_layer("Top Silk", chosen_layers["top"]["silk"], z_top , SILK_THICKNESS)
            z_top -= PASTE_THICKNESS
            plot_layer("Top Paste", chosen_layers["top"]["paste"], z_top , PASTE_THICKNESS)
            z_top -= PASTE_THICKNESS

            # Bottom layers
            z_bottom = BOARD_THICKNESS
            plot_layer("Bottom Copper", chosen_layers["bottom"]["copper"], z_bottom, COPPER_THICKNESS)
            z_bottom += COPPER_THICKNESS
            plot_layer("Bottom Mask", chosen_layers["bottom"]["mask"], z_bottom, MASK_THICKNESS)
            z_bottom += MASK_THICKNESS
            plot_layer("Bottom Silk", chosen_layers["bottom"]["silk"], z_bottom, SILK_THICKNESS)
            z_bottom += SILK_THICKNESS
            plot_layer("Bottom Paste", chosen_layers["bottom"]["paste"], z_bottom, PASTE_THICKNESS)
            z_bottom += PASTE_THICKNESS

            # Inner layers
            n_inner = len(chosen_layers["inner"])
            if n_inner > 0:
                core_height = BOARD_THICKNESS - (COPPER_THICKNESS * 2) - (MASK_THICKNESS * 2)
                layer_spacing = core_height / (n_inner + 1) if n_inner > 1 else core_height / 2
                current_z = BOARD_THICKNESS - MASK_THICKNESS - COPPER_THICKNESS
                for idx, lname in enumerate(chosen_layers["inner"], start=1):
                    zpos = current_z - (idx * layer_spacing)
                    plot_layer(f"Inner {idx}", lname, zpos, COPPER_THICKNESS)

            # -------------------------
            # Drill holes
            # -------------------------
            drills = []
            for name, layer in self.layers.items():
                lname = name.lower()
                if lname.endswith(('.drl', '.txt', '.xln')) or 'drill' in lname:
                    for item in layer["items"]:
                        try:
                            rect = item.sceneBoundingRect() if hasattr(item, "sceneBoundingRect") else item.boundingRect()
                            center = rect.center()
                            dia = max(rect.width(), rect.height())
                            if dia > 0:
                                drills.append((center.x(), center.y(), dia))
                        except Exception:
                            pass

            for x, y, dia in drills:
                if dia <= 0:
                    continue
                try:
                    cylinder = trimesh.creation.cylinder(radius=dia / 2.0,
                                                         height= 1.1*HOLE_HEIGHT,
                                                         sections=32)
                    cylinder.apply_translation([x, y, HOLE_HEIGHT / 2.0])
                    pv_mesh = pv.wrap(cylinder)
                    actor = plotter.add_mesh(pv_mesh, color=[1, 0, 0], opacity=0.9, name=f"Drill {x:.1f},{y:.1f}")
                except Exception as e:
                    print(f"Drill error: {e}")

            # -------------------------
            # Visibility checkboxes
            # -------------------------
            checkbox_y_pos = 10
            def create_visibility_callback(actor):
                def toggle_visibility(state):
                    actor.SetVisibility(state)
                return toggle_visibility

            for name in sorted(layer_actors.keys()):
                actor = layer_actors[name]
                plotter.add_checkbox_button_widget(
                    create_visibility_callback(actor), value=True, position=(10, checkbox_y_pos),
                    size=20, border_size=1, color_on='blue', color_off='grey'
                )
                plotter.add_text(name, position=(40, checkbox_y_pos + 5), font_size=8, color='white')
                checkbox_y_pos += 30

            plotter.add_axes()
            plotter.enable_parallel_projection()
            plotter.camera_position = 'iso'

            plotter.show(title="3D PCB View by Mohamed Boudour, Eng")


          

    def add_context_menu(plotter):
        # Use the interactor widget (QtInteractor)
        interactor = plotter.interactor

        def custom_context_menu(pos):
            menu = QMenu(interactor)

            change_bg = menu.addAction("Change Background Color")
            reset_cam = menu.addAction("Reset Camera")
            white_bg = menu.addAction("Set White Background")
            black_bg = menu.addAction("Set Black Background")

            action = menu.exec_(interactor.mapToGlobal(pos))

            if action == change_bg:
                color = QColorDialog.getColor()
                if color.isValid():
                    r, g, b, _ = color.getRgbF()
                    plotter.set_background((r, g, b))
                    plotter.render()
            elif action == reset_cam:
                plotter.camera_position = 'iso'
                plotter.reset_camera()
                plotter.render()
            elif action == white_bg:
                plotter.set_background("white")
                plotter.render()
            elif action == black_bg:
                plotter.set_background("black")
                plotter.render()

        # Attach handler to the Qt widget
        interactor.setContextMenuPolicy(Qt.CustomContextMenu)
        interactor.customContextMenuRequested.connect(custom_context_menu)




    def export_to_3d1(self):
            """
            Generates a 3D PyVista plot of the PCB, including layered copper, mask,
            silkscreen data, and drilled holes (rendered as cylinders).
            """
            if not self.board_outline_polygons:
                QMessageBox.warning(self, "Missing Outline", "Load a board outline first!")
                return

            # -------------------------
            # Thicknesses
            # -------------------------
            unitFactor = 1
            if self.units == "inch":
                unitFactor = 25.4
                
            BOARD_THICKNESS = 1.6 / unitFactor
            COPPER_THICKNESS = 0.035 / unitFactor
            SILK_THICKNESS = 0.015 / unitFactor
            MASK_THICKNESS = 0.01 / unitFactor
            PASTE_THICKNESS = 0.1 / unitFactor
            EPSILON = 0.001 / unitFactor
            HOLE_HEIGHT = BOARD_THICKNESS + COPPER_THICKNESS + SILK_THICKNESS + MASK_THICKNESS + PASTE_THICKNESS + EPSILON 
            # -------------------------
            # Helper to auto-detect layers
            # -------------------------

            def auto_detect_layer(patterns):
                """
                Try to detect a layer name by matching multiple patterns (extensions or keywords).
                `patterns` can be a list of regex strings.
                """
                for lname in self.layers.keys():
                    for pat in patterns:
                        if re.search(pat, lname, re.IGNORECASE):
                            return lname
                return None
                    # -------------------------
            # Part 1: Layer Selection Dialog
            # -------------------------
            dialog = QDialog(self)
            dialog.setWindowTitle("Select Layers for 3D View")
            layout = QVBoxLayout(dialog)

            def add_layer_selector(label_text, default_layer=None):
                hl = QHBoxLayout()
                lbl = QLabel(label_text)
                combo = QComboBox()
                combo.addItem("(none)")
                for lname in self.layers.keys():
                    combo.addItem(lname)
                if default_layer and default_layer in self.layers:
                    combo.setCurrentText(default_layer)  # pre-select detected layer
                hl.addWidget(lbl)
                hl.addWidget(combo)
                layout.addLayout(hl)
                return combo

            top_copper    = add_layer_selector("Top Copper",
                                                 auto_detect_layer([r"\.gtl$", r"top.*copper", r"top[^a-z0-9]*"]))
            top_silk      = add_layer_selector("Top Silkscreen",
                                                 auto_detect_layer([r"\.gto$", r"top.*silk"]))
            top_mask      = add_layer_selector("Top Mask",
                                                 auto_detect_layer([r"\.gts$", r"top.*mask"]))
            top_paste     = add_layer_selector("Top Paste",
                                                 auto_detect_layer([r"\.gtp$", r"top.*paste"]))

            bottom_copper = add_layer_selector("Bottom Copper",
                                                 auto_detect_layer([r"\.gbl$", r"bottom.*copper", r"bot[^a-z0-9]*"]))
            bottom_silk   = add_layer_selector("Bottom Silkscreen",
                                                 auto_detect_layer([r"\.gbo$", r"bottom.*silk"]))
            bottom_mask   = add_layer_selector("Bottom Mask",
                                                 auto_detect_layer([r"\.gbs$", r"bottom.*mask"]))
            bottom_paste  = add_layer_selector("Bottom Paste",
                                                 auto_detect_layer([r"\.gbp$", r"bottom.*paste"]))

            inner_combos  = [add_layer_selector(f"Inner Layer {i}",
                                                 auto_detect_layer([rf"\.g{i}l$", rf"inner\s*{i}"]))
                                 for i in range(1, 17)]


            # OK / Cancel buttons
            btns = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Cancel")
            btns.addWidget(ok_btn)
            btns.addWidget(cancel_btn)
            layout.addLayout(btns)
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            if dialog.exec_() != QDialog.Accepted:
                return

            chosen_layers = {
                "top": {"copper": top_copper.currentText(), "silk": top_silk.currentText(),
                        "paste": top_paste.currentText(), "mask": top_mask.currentText()},
                "bottom": {"copper": bottom_copper.currentText(), "silk": bottom_silk.currentText(),
                           "paste": bottom_paste.currentText(), "mask": bottom_mask.currentText()},
                "inner": [combo.currentText() for combo in inner_combos if combo.currentText() != "(none)"]
            }

            # -------------------------
            # Part 2: Board Outline
            # -------------------------
            valid_outlines = [p for p in self.board_outline_polygons if p.is_valid and not p.is_empty and p.area > 1e-6]
            if not valid_outlines:
                QMessageBox.critical(self, "Invalid Outline", "No valid board shape found!")
                return

            board_shape = unary_union(valid_outlines)
            if board_shape.geom_type == 'MultiPolygon':
                board_shape = max(board_shape.geoms, key=lambda p: p.area)
            if not board_shape.is_valid or board_shape.is_empty:
                board_shape = board_shape.buffer(0)
            if board_shape.is_empty or not board_shape.is_valid:
                QMessageBox.critical(self, "Invalid Outline", "No valid board polygon after cleanup.")
                return

            # -------------------------
            # Part 3: 3D Mesh Generation
            # -------------------------
            plotter = pv.Plotter(window_size=[1200, 800])
            plotter.set_background("black")
            layer_actors = {}

            try:
                board_mesh_trimesh = trimesh.creation.extrude_polygon(board_shape, height=BOARD_THICKNESS + EPSILON)
                # FIX: Removed the .convex_hull call to preserve non-rectangular shapes.
                # board_mesh_trimesh = board_mesh_trimesh.convex_hull 
                board_mesh_pv = pv.wrap(board_mesh_trimesh)
                actor = plotter.add_mesh(board_mesh_pv, color="#006600", name="Board Substrate")
                layer_actors["Board Substrate"] = actor
            except Exception as e:
                QMessageBox.critical(self, "3D Error", f"Board mesh failed:\n{str(e)}")
                return

            # -------------------------
            # Helper to plot a layer
            # -------------------------
            def plot_layer(display_name, gerber_name, z_start, height):
                if gerber_name not in self.layers or gerber_name == "(none)":
                    return
                layer = self.layers[gerber_name]
                if not layer["group"].isVisible():
                    return

                brush = layer.get("brush", QBrush(QColor(200, 100, 50)))
                color = brush.color()
                rgba_color = [color.redF(), color.greenF(), color.blueF(), 1.0]

                polys = self._extract_polygons_from_items(layer["items"])
                layer_meshes = []
                for poly in polys:
                    if poly.is_empty or not poly.is_valid:
                        continue
                    try:
                        mesh = trimesh.creation.extrude_polygon(poly, height=max(height, EPSILON))
                        mesh.apply_translation([0, 0, z_start])
                        layer_meshes.append(mesh)
                    except Exception as e:
                        print(f"Extrusion error for {display_name}: {e}")

                if not layer_meshes:
                    return

                combined_mesh = trimesh.util.concatenate(layer_meshes)
                pv_mesh = pv.wrap(combined_mesh)
                actor = plotter.add_mesh(pv_mesh, color=rgba_color[:3], opacity=rgba_color[3], name=display_name)
                layer_actors[display_name] = actor

            # -------------------------
            # Layer Stacking
            # -------------------------
            # Top layers
            z_top = 0
            z_top -= COPPER_THICKNESS
            plot_layer("Top Copper", chosen_layers["top"]["copper"], z_top , COPPER_THICKNESS)
            z_top -= MASK_THICKNESS
            plot_layer("Top Mask", chosen_layers["top"]["mask"], z_top , MASK_THICKNESS)
            z_top -= SILK_THICKNESS
            plot_layer("Top Silk", chosen_layers["top"]["silk"], z_top , SILK_THICKNESS)
            z_top -= PASTE_THICKNESS
            plot_layer("Top Paste", chosen_layers["top"]["paste"], z_top , PASTE_THICKNESS)
            z_top -= PASTE_THICKNESS

            # Bottom layers
            z_bottom = BOARD_THICKNESS
            plot_layer("Bottom Copper", chosen_layers["bottom"]["copper"], z_bottom, COPPER_THICKNESS)
            z_bottom += COPPER_THICKNESS
            plot_layer("Bottom Mask", chosen_layers["bottom"]["mask"], z_bottom, MASK_THICKNESS)
            z_bottom += MASK_THICKNESS
            plot_layer("Bottom Silk", chosen_layers["bottom"]["silk"], z_bottom, SILK_THICKNESS)
            z_bottom += SILK_THICKNESS
            plot_layer("Bottom Paste", chosen_layers["bottom"]["paste"], z_bottom, PASTE_THICKNESS)
            z_bottom += PASTE_THICKNESS

            # Inner layers
            n_inner = len(chosen_layers["inner"])
            if n_inner > 0:
                core_height = BOARD_THICKNESS - (COPPER_THICKNESS * 2) - (MASK_THICKNESS * 2)
                layer_spacing = core_height / (n_inner + 1) if n_inner > 1 else core_height / 2
                current_z = BOARD_THICKNESS - MASK_THICKNESS - COPPER_THICKNESS
                for idx, lname in enumerate(chosen_layers["inner"], start=1):
                    zpos = current_z - (idx * layer_spacing)
                    plot_layer(f"Inner {idx}", lname, zpos, COPPER_THICKNESS)

            # -------------------------
            # Drill holes
            # -------------------------
            drills = []
            for name, layer in self.layers.items():
                lname = name.lower()
                if lname.endswith(('.drl', '.txt', '.xln')) or 'drill' in lname:
                    for item in layer["items"]:
                        try:
                            rect = item.sceneBoundingRect() if hasattr(item, "sceneBoundingRect") else item.boundingRect()
                            center = rect.center()
                            dia = max(rect.width(), rect.height())
                            if dia > 0:
                                drills.append((center.x(), center.y(), dia))
                        except Exception:
                            pass

            for x, y, dia in drills:
                if dia <= 0:
                    continue
                try:
                    cylinder = trimesh.creation.cylinder(radius=dia / 2.0,
                                                         height= 1.1*HOLE_HEIGHT,
                                                         sections=32)
                    cylinder.apply_translation([x, y, HOLE_HEIGHT / 2.0])
                    pv_mesh = pv.wrap(cylinder)
                    actor = plotter.add_mesh(pv_mesh, color=[1, 0, 0], opacity=0.9, name=f"Drill {x:.1f},{y:.1f}")
                except Exception as e:
                    print(f"Drill error: {e}")

            # -------------------------
            # Visibility checkboxes
            # -------------------------
            checkbox_y_pos = 10
            def create_visibility_callback(actor):
                def toggle_visibility(state):
                    actor.SetVisibility(state)
                return toggle_visibility

            for name in sorted(layer_actors.keys()):
                actor = layer_actors[name]
                plotter.add_checkbox_button_widget(
                    create_visibility_callback(actor), value=True, position=(10, checkbox_y_pos),
                    size=20, border_size=1, color_on='blue', color_off='grey'
                )
                plotter.add_text(name, position=(40, checkbox_y_pos + 5), font_size=8, color='white')
                checkbox_y_pos += 30

            plotter.add_axes()
            plotter.enable_parallel_projection()
            plotter.camera_position = 'iso'
            plotter.show(title="3D PCB View by Mohamed Boudour, Eng")
            
    def export_to_3d0(self):
        """
        Generates a 3D PyVista plot of the PCB, including layered copper, mask,
        silkscreen data, and drilled holes (rendered as cylinders).
        """
        if not self.board_outline_polygons:
            QMessageBox.warning(self, "Missing Outline", "Load a board outline first!")
            return

        # -------------------------
        # Thicknesses
        # -------------------------
        unitFactor = 1
        if self.units == "inch":
            unitFactor = 25.4
            
        BOARD_THICKNESS = 1.6 / unitFactor
        COPPER_THICKNESS = 0.035 / unitFactor
        SILK_THICKNESS = 0.015 / unitFactor
        MASK_THICKNESS = 0.01 / unitFactor
        PASTE_THICKNESS = 0.1 / unitFactor
        EPSILON = 0.001 / unitFactor
        HOLE_HEIGHT = BOARD_THICKNESS + COPPER_THICKNESS + SILK_THICKNESS + MASK_THICKNESS + PASTE_THICKNESS + EPSILON 
        # -------------------------
        # Helper to auto-detect layers
        # -------------------------

        def auto_detect_layer(patterns):
            """
            Try to detect a layer name by matching multiple patterns (extensions or keywords).
            `patterns` can be a list of regex strings.
            """
            for lname in self.layers.keys():
                for pat in patterns:
                    if re.search(pat, lname, re.IGNORECASE):
                        return lname
            return None
                # -------------------------
        # Part 1: Layer Selection Dialog
        # -------------------------
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Layers for 3D View")
        layout = QVBoxLayout(dialog)

        def add_layer_selector(label_text, default_layer=None):
            hl = QHBoxLayout()
            lbl = QLabel(label_text)
            combo = QComboBox()
            combo.addItem("(none)")
            for lname in self.layers.keys():
                combo.addItem(lname)
            if default_layer and default_layer in self.layers:
                combo.setCurrentText(default_layer)  # pre-select detected layer
            hl.addWidget(lbl)
            hl.addWidget(combo)
            layout.addLayout(hl)
            return combo

        top_copper    = add_layer_selector("Top Copper",
                                           auto_detect_layer([r"\.gtl$", r"top.*copper", r"top[^a-z0-9]*"]))
        top_silk      = add_layer_selector("Top Silkscreen",
                                           auto_detect_layer([r"\.gto$", r"top.*silk"]))
        top_mask      = add_layer_selector("Top Mask",
                                           auto_detect_layer([r"\.gts$", r"top.*mask"]))
        top_paste     = add_layer_selector("Top Paste",
                                           auto_detect_layer([r"\.gtp$", r"top.*paste"]))

        bottom_copper = add_layer_selector("Bottom Copper",
                                           auto_detect_layer([r"\.gbl$", r"bottom.*copper", r"bot[^a-z0-9]*"]))
        bottom_silk   = add_layer_selector("Bottom Silkscreen",
                                           auto_detect_layer([r"\.gbo$", r"bottom.*silk"]))
        bottom_mask   = add_layer_selector("Bottom Mask",
                                           auto_detect_layer([r"\.gbs$", r"bottom.*mask"]))
        bottom_paste  = add_layer_selector("Bottom Paste",
                                           auto_detect_layer([r"\.gbp$", r"bottom.*paste"]))

        inner_combos  = [add_layer_selector(f"Inner Layer {i}",
                                           auto_detect_layer([rf"\.g{i}l$", rf"inner\s*{i}"]))
                         for i in range(1, 17)]


        # OK / Cancel buttons
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        if dialog.exec_() != QDialog.Accepted:
            return

        chosen_layers = {
            "top": {"copper": top_copper.currentText(), "silk": top_silk.currentText(),
                    "paste": top_paste.currentText(), "mask": top_mask.currentText()},
            "bottom": {"copper": bottom_copper.currentText(), "silk": bottom_silk.currentText(),
                       "paste": bottom_paste.currentText(), "mask": bottom_mask.currentText()},
            "inner": [combo.currentText() for combo in inner_combos if combo.currentText() != "(none)"]
        }

        # -------------------------
        # Part 2: Board Outline
        # -------------------------
        valid_outlines = [p for p in self.board_outline_polygons if p.is_valid and not p.is_empty and p.area > 1e-6]
        if not valid_outlines:
            QMessageBox.critical(self, "Invalid Outline", "No valid board shape found!")
            return

        board_shape = unary_union(valid_outlines)
        if board_shape.geom_type == 'MultiPolygon':
            board_shape = max(board_shape.geoms, key=lambda p: p.area)
        if not board_shape.is_valid or board_shape.is_empty:
            board_shape = board_shape.buffer(0)
        if board_shape.is_empty or not board_shape.is_valid:
            QMessageBox.critical(self, "Invalid Outline", "No valid board polygon after cleanup.")
            return

        # -------------------------
        # Part 3: 3D Mesh Generation
        # -------------------------
        plotter = pv.Plotter(window_size=[1200, 800])
        plotter.set_background("black")
        layer_actors = {}

        try:
            board_mesh_trimesh = trimesh.creation.extrude_polygon(board_shape, height=BOARD_THICKNESS + EPSILON)
            board_mesh_trimesh = board_mesh_trimesh.convex_hull
            board_mesh_pv = pv.wrap(board_mesh_trimesh)
            actor = plotter.add_mesh(board_mesh_pv, color="#006600", name="Board Substrate")
            layer_actors["Board Substrate"] = actor
        except Exception as e:
            QMessageBox.critical(self, "3D Error", f"Board mesh failed:\n{str(e)}")
            return

        # -------------------------
        # Helper to plot a layer
        # -------------------------
        def plot_layer(display_name, gerber_name, z_start, height):
            if gerber_name not in self.layers or gerber_name == "(none)":
                return
            layer = self.layers[gerber_name]
            if not layer["group"].isVisible():
                return

            brush = layer.get("brush", QBrush(QColor(200, 100, 50)))
            color = brush.color()
            rgba_color = [color.redF(), color.greenF(), color.blueF(), 1.0]

            polys = self._extract_polygons_from_items(layer["items"])
            layer_meshes = []
            for poly in polys:
                if poly.is_empty or not poly.is_valid:
                    continue
                try:
                    mesh = trimesh.creation.extrude_polygon(poly, height=max(height, EPSILON))
                    mesh.apply_translation([0, 0, z_start])
                    layer_meshes.append(mesh)
                except Exception as e:
                    print(f"Extrusion error for {display_name}: {e}")

            if not layer_meshes:
                return

            combined_mesh = trimesh.util.concatenate(layer_meshes)
            pv_mesh = pv.wrap(combined_mesh)
            actor = plotter.add_mesh(pv_mesh, color=rgba_color[:3], opacity=rgba_color[3], name=display_name)
            layer_actors[display_name] = actor

        # -------------------------
        # Layer Stacking
        # -------------------------
        # Top layers
        z_top = 0
        z_top -= COPPER_THICKNESS
        plot_layer("Top Copper", chosen_layers["top"]["copper"], z_top , COPPER_THICKNESS)
        z_top -= MASK_THICKNESS
        plot_layer("Top Mask", chosen_layers["top"]["mask"], z_top , MASK_THICKNESS)
        z_top -= SILK_THICKNESS
        plot_layer("Top Silk", chosen_layers["top"]["silk"], z_top , SILK_THICKNESS)
        z_top -= PASTE_THICKNESS
        plot_layer("Top Paste", chosen_layers["top"]["paste"], z_top , PASTE_THICKNESS)
        z_top -= PASTE_THICKNESS

        # Bottom layers
        z_bottom = BOARD_THICKNESS
        plot_layer("Bottom Copper", chosen_layers["bottom"]["copper"], z_bottom, COPPER_THICKNESS)
        z_bottom += COPPER_THICKNESS
        plot_layer("Bottom Mask", chosen_layers["bottom"]["mask"], z_bottom, MASK_THICKNESS)
        z_bottom += MASK_THICKNESS
        plot_layer("Bottom Silk", chosen_layers["bottom"]["silk"], z_bottom, SILK_THICKNESS)
        z_bottom += SILK_THICKNESS
        plot_layer("Bottom Paste", chosen_layers["bottom"]["paste"], z_bottom, PASTE_THICKNESS)
        z_bottom += PASTE_THICKNESS

        # Inner layers
        n_inner = len(chosen_layers["inner"])
        if n_inner > 0:
            core_height = BOARD_THICKNESS - (COPPER_THICKNESS * 2) - (MASK_THICKNESS * 2)
            layer_spacing = core_height / (n_inner + 1) if n_inner > 1 else core_height / 2
            current_z = BOARD_THICKNESS - MASK_THICKNESS - COPPER_THICKNESS
            for idx, lname in enumerate(chosen_layers["inner"], start=1):
                zpos = current_z - (idx * layer_spacing)
                plot_layer(f"Inner {idx}", lname, zpos, COPPER_THICKNESS)

        # -------------------------
        # Drill holes
        # -------------------------
        drills = []
        for name, layer in self.layers.items():
            lname = name.lower()
            if lname.endswith(('.drl', '.txt', '.xln')) or 'drill' in lname:
                for item in layer["items"]:
                    try:
                        rect = item.sceneBoundingRect() if hasattr(item, "sceneBoundingRect") else item.boundingRect()
                        center = rect.center()
                        dia = max(rect.width(), rect.height())
                        if dia > 0:
                            drills.append((center.x(), center.y(), dia))
                    except Exception:
                        pass

        for x, y, dia in drills:
            if dia <= 0:
                continue
            try:
                cylinder = trimesh.creation.cylinder(radius=dia / 2.0,
                                                     height= 1.1*HOLE_HEIGHT,
                                                     sections=32)
                cylinder.apply_translation([x, y, HOLE_HEIGHT / 2.0])
                pv_mesh = pv.wrap(cylinder)
                actor = plotter.add_mesh(pv_mesh, color=[1, 0, 0], opacity=0.9, name=f"Drill {x:.1f},{y:.1f}")
            except Exception as e:
                print(f"Drill error: {e}")

        # -------------------------
        # Visibility checkboxes
        # -------------------------
        checkbox_y_pos = 10
        def create_visibility_callback(actor):
            def toggle_visibility(state):
                actor.SetVisibility(state)
            return toggle_visibility

        for name in sorted(layer_actors.keys()):
            actor = layer_actors[name]
            plotter.add_checkbox_button_widget(
                create_visibility_callback(actor), value=True, position=(10, checkbox_y_pos),
                size=20, border_size=1, color_on='blue', color_off='grey'
            )
            plotter.add_text(name, position=(40, checkbox_y_pos + 5), font_size=8, color='white')
            checkbox_y_pos += 30

        plotter.add_axes()
        plotter.enable_parallel_projection()
        plotter.camera_position = 'iso'
        plotter.show(title="3D PCB View by Mohamed Boudour, Eng")



    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Gerber", "", "Gerber (*.*);;All (*)"
        )
        if not paths:
            return

        # Load all files first into a temporary list
        loaded_layers = []
        for path in paths:
            name = os.path.basename(path)
            if name in self.layers:
                continue
            items = self.parse_gerber(path)
            if not items:
                continue

            # Assign colors based on layer type
            lname = name.lower()
            if lname.endswith(".gtl"):
                color = QColor(255, 0, 0)  # red top copper
            elif lname.endswith(".gbl"):
                color = QColor(0, 0, 255)  # blue bottom copper
            else:
                color = QColor.fromHsl(random.randint(0, 359), 255, 200)

            brush = QBrush(color)
            loaded_layers.append((name, items, brush))

        # Define the desired order
        order_priority = [
            ".gbp", ".gbo", ".gbs", ".gbl",
            "OTHER",
            ".gtl", ".gts", ".gto", ".gtp"
        ]

        def layer_sort_key(layer_tuple):
            name, _, _ = layer_tuple
            lname = name.lower()
            for idx, ext in enumerate(order_priority):
                if ext == "OTHER":
                    continue
                if lname.endswith(ext):
                    return idx
            return order_priority.index("OTHER")  # unknown layers

        # Sort layers
        loaded_layers.sort(key=layer_sort_key)

        # Now add to scene and list in sorted order
        for name, items, brush in loaded_layers:
            scene_items = []
            for it in items:
                if isinstance(it, QPainterPath):
                    it.setFillRule(Qt.WindingFill)
                    item = self.scene.addPath(it, QPen(Qt.NoPen), brush)
                else:
                    try:
                        it.setPen(QPen(Qt.NoPen))
                        it.setBrush(brush)
                    except:
                        pass
                    self.scene.addItem(it)
                    item = it
                scene_items.append(item)

            group = self.scene.createItemGroup(scene_items)
            self.layers[name] = {"group": group, "items": scene_items, "brush": brush}

            # Add to list widget
            lw = QListWidgetItem(name)
            lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
            lw.setCheckState(Qt.Checked)
            lw.setData(Qt.UserRole, name)
            self.layer_list.addItem(lw)

        # Fit view
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)



    def open_drill_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Drill", "", "Drill (*.drl *.txt *.xln);;All (*)"
        )
        if not path:
            return

        name = os.path.basename(path)
        if name in self.layers:
            return

        items = self.parse_drill(path)
        if not items:
            return

        # Use white brush for drill layer
        brush = QBrush(QColor("white"))

        # Create scene group
        group = self.scene.createItemGroup(items)
        self.layers[name] = {"group": group, "items": items, "brush": brush, "path": path}

        # Add to QListWidget
        lw = QListWidgetItem(name)
        lw.setFlags(lw.flags() | Qt.ItemIsUserCheckable)
        lw.setCheckState(Qt.Checked)
        lw.setData(Qt.UserRole, name)
        self.layer_list.addItem(lw)

        # Add to class-level loaded_layers
        if not hasattr(self, "loaded_layers"):
            self.loaded_layers = []
        self.loaded_layers.append((name, path, items, brush))

        # Fit view
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        
    def parse_gerber(self, filepath, scene_factor=1.0):
        self.aperture_macros.clear()
        self.current_pos = QPointF(0, 0)
        self.current_aperture = None
        items = []
        polygon_mode = False
        polygon_path = None
        interpolation_mode = 'linear'
        unitfactor = 1.0  # default mm

        with open(filepath, 'r') as f:
            for raw in f:
                line = raw.strip()
                if line.startswith('%FSLA'):
                    try:
                        m = re.search(r'X(\d)(\d)', line)
                        if m: self.dec_d = int(m.group(2))
                    except: pass
                    continue

                # Detect unit
                if line.startswith('%MO'):
                    if "IN" in line.upper(): unitfactor = 25.4
                    else: unitfactor = 1.0
                    continue

                # Interpolation modes
                if line.startswith('G01'): interpolation_mode = 'linear'
                elif line.startswith('G02'): interpolation_mode = 'cw_arc'
                elif line.startswith('G03'): interpolation_mode = 'ccw_arc'

                # Aperture definitions
                if line.startswith('%ADD'):
                    m = re.match(r'%ADD(\d+)([A-Z]),(.+)\*%', line)
                    if m:
                        code = int(m.group(1))
                        shape = m.group(2)
                        parts = re.split('[Xx]', m.group(3))
                        params = []
                        for p in parts:
                            try: params.append(float(p.strip()) * unitfactor)
                            except: pass
                        if not params: params = [0.2 * unitfactor]
                        self.aperture_macros[code] = (shape, params)
                    continue

                # Polygon mode
                if line.startswith('G36'): polygon_mode, polygon_path = True, QPainterPath()
                if line.startswith('G37'):
                    polygon_mode = False
                    if polygon_path and not polygon_path.isEmpty():
                        polygon_path.closeSubpath()
                        items.append(polygon_path)

                if not line or line.startswith('%') or line.startswith('G04'): continue

                # Drawing modes
                mode = None
                if re.search(r'D0?3\*?', line): mode = 'flash'
                elif re.search(r'D0?2\*?', line): mode = 'move'
                elif re.search(r'D0?1\*?', line): mode = 'draw'

                # Aperture selection
                mdc = re.search(r'D0?(\d+)\*?', line)
                if mdc:
                    code = int(mdc.group(1))
                    if code in self.aperture_macros: self.current_aperture = code

                # Coordinates
                coords = re.findall(r'([XYIJ])(-?\d+)', line)
                vals = {}
                for axis, num_s in coords:
                    try: vals[axis] = int(num_s) / (10 ** self.dec_d) * unitfactor
                    except: pass

                x = vals.get('X', self.current_pos.x())
                y = vals.get('Y', self.current_pos.y())
                new_pos = QPointF(float(x), float(y))

                # Execute mode
                if mode == 'move':
                    self.current_pos = new_pos
                    if polygon_mode and polygon_path and polygon_path.isEmpty():
                        polygon_path.moveTo(new_pos)

                elif mode == 'draw':
                    if polygon_mode and polygon_path:
                        polygon_path.lineTo(new_pos)
                        
                    else:
                        if interpolation_mode in ('cw_arc', 'ccw_arc'):
                            i = vals.get('I', 0.0)
                            j = vals.get('J', 0.0)
                            center = QPointF(self.current_pos.x() + i, self.current_pos.y() + j)
                            path = self._create_arc_path(self.current_pos, new_pos, center, interpolation_mode == 'cw_arc')
                            if path:
                                width = self._get_aperture_width() * scene_factor
                                stroker = QPainterPathStroker()
                                stroker.setWidth(width)
                                items.append(stroker.createStroke(path))
                        else:
                            path = QPainterPath()
                            path.moveTo(self.current_pos)
                            path.lineTo(new_pos)
                            width = self._get_aperture_width() * scene_factor
                            stroker = QPainterPathStroker()
                            stroker.setWidth(width)
                            stroker.setCapStyle(Qt.RoundCap)     # rounded ends
                            stroker.setJoinStyle(Qt.RoundJoin)   # rounded corners if multiple segments
                            items.append(stroker.createStroke(path))

                    self.current_pos = new_pos

                elif mode == 'flash':
                    if not self.current_aperture or self.current_aperture not in self.aperture_macros:
                        size = 0.2 * scene_factor
                        e = QGraphicsEllipseItem(new_pos.x() - size/2, new_pos.y() - size/2, size, size)
                        items.append(e)
                    else:
                        shape, params = self.aperture_macros[self.current_aperture]
                        if shape == 'C':
                            size = params[0] * scene_factor
                            e = QGraphicsEllipseItem(new_pos.x() - size/2, new_pos.y() - size/2, size, size)
                            items.append(e)
                        elif shape == 'R':
                            w = params[0] * scene_factor
                            h = params[1] * scene_factor if len(params) > 1 else w
                            r = QGraphicsRectItem(new_pos.x() - w/2, new_pos.y() - h/2, w, h)
                            items.append(r)
                        elif shape == 'O':
                            w = params[0] * scene_factor
                            h = params[1] * scene_factor if len(params) > 1 else w
                            p = QPainterPath()
                            p.addRoundedRect(new_pos.x() - w/2, new_pos.y() - h/2, w, h, min(w,h)/2, min(w,h)/2)
                            items.append(p)
                    self.current_pos = new_pos

        # Flip Y
        transform = QTransform()
        transform.scale(1, -1)
        transformed = []
        for it in items:
            if isinstance(it, QPainterPath):
                transformed.append(transform.map(it))
            elif hasattr(it, "setTransform"):
                it.setTransform(transform, True)
                transformed.append(it)
            else:
                transformed.append(it)
        return transformed
 


    def _get_aperture_width(self):
        if not self.current_aperture or self.current_aperture not in self.aperture_macros:
            return 0.2  # largeur par défaut en mm
        _, params = self.aperture_macros[self.current_aperture]
        if not params:
            return 0.2
        # Pour éviter une "nappe blanche", on utilise le rayon (diam/2)
        return params[0] / 2


    def _create_arc_path(self, start, end, center, clockwise):
        dx1 = start.x() - center.x(); dy1 = start.y() - center.y()
        dx2 = end.x() - center.x(); dy2 = end.y() - center.y()
        radius = (dx1**2 + dy1**2)**0.5
        if radius == 0: return None
        angle1 = math.degrees(math.atan2(dy1, dx1)) % 360
        angle2 = math.degrees(math.atan2(dy2, dx2)) % 360
        if clockwise:
            sweep = (angle2 - angle1 - 360) if angle2 > angle1 else (angle2 - angle1)
        else:
            sweep = (angle2 - angle1 + 360) if angle1 > angle2 else (angle2 - angle1)
        rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        path = QPainterPath()
        path.moveTo(start)
        path.arcTo(rect, -angle1, -sweep)
        return path



    # Note: This is the class method, assuming self.dec_d exists

    def parse_drill(self, filepath):
        drill_tools = {}
        drill_hits = []
        current_tool = None
        # Initialize current_pos to QPointF(0, 0)
        current_pos = QPointF(0, 0)
        
        # Default decimal precision from class attribute (used if no explicit format is found)
        drill_decimals = self.dec_d

        # unité par défaut
        unit = "inch"
        # factor to convert to millimeters (as your comment implies conversion to mm)
        unitfactor = 25.4 
        
        # State flags
        incremental_mode = False

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    uline = line.strip().upper()

                    # Ignore comments and control characters
                    if uline.startswith(';') or uline.startswith('M48') or uline == '%':
                        continue
                    
                    # --- State/Unit Detection ---
                    if 'METRIC' in uline or 'MM' in uline:
                        unit = "mm"
                        unitfactor = 1.0
                    elif 'INCH' in uline:
                        unit = "inch"
                        unitfactor = 25.4
                    
                    # Zero Suppression / Coordinate Mode (Crucial for robustness)
                    if 'G90' in uline:
                        incremental_mode = False # Absolute mode
                    elif 'G91' in uline or 'M95' in uline:
                        incremental_mode = True # Incremental mode
                    
                    # The DipTrace file doesn't have LZ/TZ, so we skip explicit zero suppression detection
                    # but we'll handle the implied format below.

                    # --- Format décimal (ex: FORMAT=2.4) ---
                    # This handles KiCad's explicit format declaration
                    m_fmt = re.search(r'FORMAT\s*=\s*(\d+)\.(\d+)', uline)
                    if m_fmt:
                        # I = integer places, D = decimal places
                        # Your code only tracks the decimal places (D)
                        drill_decimals = int(m_fmt.group(2))

                    # --- Tool Definition (ex: T01C0.8) ---
                    m_tool = re.match(r'^T0*(\d+)\s*C\s*([0-9.]+)', uline)
                    if m_tool:
                        tool_id = int(m_tool.group(1))
                        tool_dia = float(m_tool.group(2)) * unitfactor
                        drill_tools[tool_id] = tool_dia

                    # --- Tool Selection (ex: T01) ---
                    if uline.startswith('T') and 'C' not in uline:
                        m_sel = re.match(r'^T0*(\d+)', uline)
                        if m_sel:
                            current_tool = int(m_sel.group(1))

                    # --- Extraction and Calculation of Coordinates ---
                    coords = {}
                    
                    # 1. Look for coordinates with an explicit decimal point (KiCad style)
                    for axis, val in re.findall(r'([XY])([+-]?[0-9]*\.[0-9]+)', line, re.IGNORECASE):
                        coords[axis.upper()] = float(val)

                    # 2. Look for coordinates without a decimal point (DipTrace style)
                    # This ensures we don't double-count coordinates that have a decimal.
                    if not coords:
                        for axis, val in re.findall(r'([XY])([+-]?[0-9]+)', line, re.IGNORECASE):
                            # The coordinate string value (e.g., '039140')
                            clean_val = val.lstrip('+-') 
                            
                            # CRITICAL FIX FOR DIPTRACE:
                            # If the value is 6 digits long and has no decimal point, assume 4 decimal places (2:4 format).
                            # This overrides any default/inferred precision.
                            if len(clean_val) == 6:
                                temp_decimals = 4
                            else:
                                # Use the precision set by FORMAT=... or the default
                                temp_decimals = drill_decimals 
                            
                            # Convert integer string to float based on precision
                            coords[axis.upper()] = int(val) / (10 ** temp_decimals)

                    if coords:
                        # Get the X and Y movement values, default to 0.0 if not present in the line
                        x_move = coords.get('X', 0.0)
                        y_move = coords.get('Y', 0.0)

                        # Update position based on mode
                        if incremental_mode:
                            x = current_pos.x() + unitfactor * x_move
                            y = current_pos.y() + unitfactor * y_move
                        else: # Absolute mode (default and most common)
                            # Only update if the coordinate is explicitly given in the line
                            x = unitfactor * x_move if 'X' in coords else current_pos.x()
                            y = unitfactor * y_move if 'Y' in coords else current_pos.y()
                        
                        # Store new position for next line's reference
                        current_pos = QPointF(x, y)

                        # --- Create the Drill Hit if a valid tool is selected ---
                        if current_tool in drill_tools:
                            dia = drill_tools[current_tool]

                            if dia > 0:
                                # Create the ellipse centered at (x, y)
                                e = QGraphicsEllipseItem(x - dia / 2, y - dia / 2, dia, dia)

                                # Transformation Y-flip (for display consistency)
                                t = QTransform()
                                t.scale(1, -1)
                                e.setTransform(t, True)

                                # Visual Style (Uses 'white' brush specified in open_drill_file)
                                e.setBrush(QBrush(QColor("white")))
                                e.setPen(QPen(Qt.NoPen))

                                drill_hits.append(e)

                print(f"Drill file unit: {unit} (Factor: {unitfactor}) → converted to mm")
                
                # Print the final inferred decimal count for debugging
                if 'INCH' in uline and not m_fmt:
                     print(f"Heuristic applied: Assumed {4} decimal places for integer coordinates.")


        except Exception as e:
            print(f"Drill parse error: {e}")
            return []

        return drill_hits
    
        
    def parse_drill0(self, filepath):
        drill_tools = {}
        drill_hits = []
        current_tool = None
        current_pos = QPointF(0, 0)
        drill_decimals = self.dec_d

        # unité par défaut
        unit = "inch"
        unitfactor = 25.4

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    uline = line.strip().upper()

                    # --- Détection des unités ---
                    if 'METRIC' in uline or 'MM' in uline:
                        unit = "mm"
                        unitfactor = 1.0
                    elif 'INCH' in uline:
                        unit = "inch"
                        unitfactor = 25.4

                    # --- Format décimal (ex: FORMAT=2.4) ---
                    m_fmt = re.search(r'FORMAT\s*=\s*(\d+)\.(\d+)', uline)
                    if m_fmt:
                        drill_decimals = int(m_fmt.group(2))

                    # --- Définition d'un outil (ex: T01C0.8) ---
                    m_tool = re.match(r'^T0*(\d+)\s*C\s*([0-9.]+)', uline)
                    if m_tool:
                        tool_id = int(m_tool.group(1))
                        tool_dia = float(m_tool.group(2)) * unitfactor
                        drill_tools[tool_id] = tool_dia

                    # --- Sélection de l’outil courant ---
                    if uline.startswith('T') and 'C' not in uline:
                        m_sel = re.match(r'^T0*(\d+)', uline)
                        if m_sel:
                            current_tool = int(m_sel.group(1))

                    # --- Extraction des coordonnées ---
                    coords = {}
                    for axis, val in re.findall(r'([XY])(-?[0-9.]+)', line, re.IGNORECASE):
                        if '.' in val:
                            coords[axis.upper()] = float(val)
                        else:
                            coords[axis.upper()] = int(val) / (10 ** drill_decimals)

                    if coords:
                        x = unitfactor * coords.get('X', current_pos.x())
                        y = unitfactor * coords.get('Y', current_pos.y())
                        current_pos = QPointF(x, y)

                        # --- Création d’un perçage si outil valide ---
                        if current_tool in drill_tools:
                            dia = drill_tools[current_tool]

                            if dia > 0:
                                # Création de l'ellipse
                                e = QGraphicsEllipseItem(x - dia / 2, y - dia / 2, dia, dia)

                                # Transformation Y-flip (comme parse_gerber)
                                t = QTransform()
                                t.scale(1, -1)
                                e.setTransform(t, True)

                                # Style visuel
                                e.setBrush(QBrush(QColor("white")))
                                e.setPen(QPen(Qt.NoPen))

                                drill_hits.append(e)

            print("Drill file unit:", unit, "→ converti en mm")

        except Exception as e:
            print(f"Drill parse error: {e}")
            return []

        return drill_hits

    # Other methods (toggle, mirror, etc.) omitted for brevity but work as before

    def toggle_layer(self, item):
        name = item.data(Qt.UserRole)
        layer = self.layers.get(name)
        if layer: layer["group"].setVisible(item.checkState() == Qt.Checked)
    def toggle_mirror(self):
        self.mirrored = not self.mirrored
        self.update_transforms()
    def rotate_layers(self):
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.update_transforms()
    def update_transforms(self):
        for info in self.layers.values():
            grp = info["group"]
            rect = grp.boundingRect()
            cx, cy = rect.center().x(), rect.center().y()
            t = QTransform()
            t.translate(cx, cy)
            t.rotate(self.rotation_angle)
            if self.mirrored: t.scale(-1, 1)
            t.translate(-cx, -cy)
            grp.setTransform(t)
    def update_mouse_position(self, pos):
        self.coord_label.setText(f"X={pos.x():.3f}, Y={pos.y():.3f}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = GerberViewer()
    viewer.show()
    sys.exit(app.exec_())
