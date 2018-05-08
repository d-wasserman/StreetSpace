"""Functions to manipulate Shapely geometries."""

##############################################################################
# Module: geometry.py
# Description: Functions to manipulate Shapely geometries.
# License: MIT
##############################################################################

import shapely as sh
import numpy as np
import matplotlib.pyplot as plt
import geopandas as gpd
import pandas as pd
import osmnx as ox
import mplleaflet
import random
import matplotlib
from shapely.ops import linemerge
from shapely.geometry import (Point, MultiPoint, LineString, MultiLineString,
    Polygon, MultiPolygon, GeometryCollection)
from math import radians, cos, sin, asin, sqrt, ceil
from geopandas import GeoDataFrame
from rtree import index
from itertools import cycle
from pprint import pprint
from time import time

from .utils import *

def vertices_to_points(geometry):
    """Convert vertices of a Shapely LineString or Polygon into points.

    Parameters
    ----------
    geometry : :class:`shapely.geometry.LineString`
        LineString whose vertices will be converted to Points.
   
    Returns
    -------
    :obj:`list`
        List of :class:`shapely.geometry.Point`.
    """
    if isinstance(geometry, Polygon):
        xs, ys = geometry.exterior.coords.xy
        xs = xs[:-1] # Exclude redundant closing vertex
        ys = ys[:-1]
    elif isinstance(geometry, LineString):
        xs, ys = geometry.coords.xy
    points = [sh.geometry.Point(xy[0], xy[1]) for xy in list(zip(xs, ys))]
    return points


def extend_line(linestring, extend_dist, ends='both'):
    """Extend a LineString at either end.

    Extensions will follow the same azimuth as the endmost segment(s).

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to extend
    extend_dist : :obj:`float`
        Distance to extend
    ends : :obj:`str`, optional, default = ``'both'``
        * ``'both'`` : Extend from both ends
        * ``'start'`` : Extend from start only
        * ``'end'`` : Extend from end only
    
    Returns
    -------
    :class:`shapely.geometry.LineString`
        Extended LineString
    """
    
    if ends == 'both':
        endpoints = [sh.geometry.Point(linestring.coords[0]),
                     sh.geometry.Point(linestring.coords[-1])]
        adjacent_points = [sh.geometry.Point(linestring.coords[1]),
                           sh.geometry.Point(linestring.coords[-2])]
    elif ends == 'start':
        endpoints = [sh.geometry.Point(linestring.coords[0])]
        adjacent_points = [sh.geometry.Point(linestring.coords[1])]
    elif ends == 'end':
        endpoints = [sh.geometry.Point(linestring.coords[-1])]
        adjacent_points = [sh.geometry.Point(linestring.coords[-2])]
    # Draw extensions on one or both ends:
    new_segments = []
    for endpoint, adjacent_point in zip(endpoints, adjacent_points):
        # Get the azimuth of the last segment:
        azimuth = np.arctan2(np.subtract(endpoint.x, adjacent_point.x),
                             np.subtract(endpoint.y, adjacent_point.y))
        # Construct a new endpoint along the extension of that segment:
        new_endpoint_x = np.sin(azimuth) * extend_dist + endpoint.x
        new_endpoint_y = np.cos(azimuth) * extend_dist + endpoint.y
        new_endpoint = sh.geometry.Point([new_endpoint_x,new_endpoint_y])
        # Draw a new segment that extends to this new end point:
        new_segments.append(sh.geometry.LineString([endpoint, new_endpoint]))
    # Merge new segments with existing linestring:
    return linemerge([linestring] + new_segments)


def shorten_line(linestring, shorten_dist, ends = 'both'):
    """Shorten a LineString at either end.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to extend
    shorten_dist : :obj:`float`
        Distance to shorten
    ends : :obj:`str`, optional, default = ``'both'``
        * ``'both'`` : Shorten from both ends
        * ``'start'`` : Shorten from start only
        * ``'end'`` : Shorten from end only
    
    Returns
    -------
    :class:`shapely.geometry.LineString`
        Shortened LineString
    """
    if ends == 'both':
        start = linestring.interpolate(shorten_dist)
        end = linestring.interpolate(linestring.length - shorten_dist)
    elif ends == 'start':
        start = linestring.interpolate(shorten_dist)
        end = endpoints(linestring)[1]
    elif ends == 'end':
        start = endpoints(linestring)[0]
        end = linestring.interpolate(linestring.length - shorten_dist)
    return segment(linestring, start, end)


def split_line_at_points(linestring, points):
    """Split a LineString into segments defined by Points along it.

    Adapted from: https://stackoverflow.com/questions/34754777/shapely-split
    -linestrings-at-intersections-with-other-linestrings

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to split

    points : :obj:`list`
        Must contain :class:`shapely.geometry.Point`

    Returns
    ----------
    :obj:`list`
        Segments as :class:`shapely.geometry.LineString`
    """

    # get original coordinates of line
    coords = list(linestring.coords)
    # break off last coordinate in case the first/last are the same (loop)
    last_coord = coords[-1]
    coords = coords[0:-1]
    # make a list identifying which coordinates will be segment endpoints
    cuts = [0] * len(coords)
    cuts[0] = 1     
    # add the coords from the cut points
    coords += [list(p.coords)[0] for p in points]    
    cuts += [1] * len(points)
    # calculate the distance along the linestring for each coordinate
    dists = [linestring.project(Point(p)) for p in coords]
    # sort the coords/cuts axd on the distances
    coords = [p for (d, p) in sorted(zip(dists, coords))]
    cuts = [p for (d, p) in sorted(zip(dists, cuts))]
    # add back last coordinate
    coords = coords + [last_coord]
    cuts = cuts + [1]
    # generate the Lines      
    linestrings = []
    for i in range(len(coords)-1):           
        if cuts[i] == 1:    
            # find next element in cuts == 1 starting from index i + 1   
            j = cuts.index(1, i + 1)    
            linestrings.append(LineString(coords[i:j+1]))
    return linestrings

def split_line_at_intersection(linestring, split_linestring):
    """Split one LineString at its points of intersection with another LineString.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to split

    split_linestring : :class:`shapely.geometry.LineString`
        LineString to split by

    Returns
    ----------
    :obj:`list`
        Segments as :class:`shapely.geometry.LineString`
    """
    points = linestring.intersection(split_linestring)
    if isinstance(points, Point):
        points = [points]
    else:
        points = [x for x in points]
    return split_line_at_points(linestring, points)


def split_line_at_dists(linestring, dists):
    """Split a LineString into segments defined by distances along it.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to split

    dists : :obj:`list`
        Must contain distances as :obj:`float`

    Returns
    ----------
    :obj:`list`
        Segments as :class:`shapely.geometry.LineString`
    """
    points = [linestring.interpolate(x) for x in dists]
    return split_line_at_points(linestring, points)


def segment(linestring, u, v):
    """Extract a LineString segment defined by two Points along it.

    The order of u and v specifies the directionality of the returned
    LineString. Directionality is not inhereted from the original LineString.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString from which to extract segment
    u : :class:`shapely.geometry.Point`
        Segment start point
    v : :class:`shapely.geometry.Point`
        Segment end point

    Returns
    ----------
    :class:`shapely.geometry.LineString`
        Segment of `linestring`
    """
    segment = split_line_at_points(linestring, [u, v])[1]
    # See if the beginning of the segment aligns with u
    if endpoints(segment)[0].equals(u):
        return segment
    # Otherwise, flip the line direction so it matches the order of u -> v
    else:
        return LineString(np.flip(np.array(segment), 0))
    return LineString(np.flip(np.array(segment), 0)) 


def closest_point_along_lines(search_point, lines, search_distance=None, 
    sindex=None):
    """Find the closest position along multiple lines.

    Parameters
    ----------
    search_point : :class:`shapely.geometry.Point`
        Point from which to search
    lines : :obj:`list` 
        Lines to search. Must be either a list of linestrings or a list of\
        (index, linestring) tuples, if linestrings have predifined indices
    search_distance : :obj:`float`, optional, default = ``None``
        Maximum distance to search from the `search_point`
    sindex : :class:`rtree.index.Index`, optional, default = ``None``
        Spatial index for list of lines (best created with ``list_sindex``)
    
    Returns
    -------
    match_point : :class:`shapely.geometry.Point`
        Location of closest point
    index : :obj:`tuple`
        Index for the closest line
    distance : :obj:`float`
        Distance from the search_point to the closest line
    """
    # Check whether lines are formatted as a list of tuples, with indices
    # in the first positions and geometries in the second positions
    
    tuples = True
    for line in lines:
        if not isinstance(line, tuple):
            tuples = False

    # If not indexed tuples, create them
    if tuples is False:
        line_tuples = [(i, x) for i, x in enumerate(lines)]
    else:
        line_tuples = lines
        
    # Pare down lines, if spatial index provided
    if sindex:
        if not search_distance:
            raise ValueError('Must specify search_distance if using spatial index')
        # Construct search bounds around the search point
        search_bounds = search_point.buffer(search_distance).bounds
        # Get indices for lines within search bounds
        line_indices = [i for i in sindex.intersection(search_bounds, 
                                                       objects='raw')]
        # Get pared lines
        line_tuples = [line_tuples[i] for i in line_indices]
    
    # Pare down lines, if only search distance provided
    elif search_distance:
        # Construct search bounds around the search point
        search_area = search_point.buffer(search_distance)
        # Get pared IDs
        line_tuples = [line_tuple for line_tuple in line_tuples if 
                       line_tuple[-1].intersects(search_area)]
   
    # Calculate the distance between the search point and each line   
    distances = []   

    for _, line in line_tuples:
        distances.append(search_point.distance(line))    
    
    if len(distances) > 0:

        if len(distances) == 1:

            i, line = line_tuples[0]
            distance = distances[0]
        
        elif len(distances) > 1:
            # Find closest line
            line_tuples = np.asarray(line_tuples, dtype='object')
            distances = np.asarray(distances, dtype='float')
            distance_array = np.column_stack((distances, line_tuples))
            distance_array = distance_array[distance_array[:,0].argsort()]
            distance = distance_array[0,0]
            i = distance_array[0,1]
            line = distance_array[0,2]

        # Find the nearest point along that line
        match_point = line.interpolate(line.project(search_point))
        return match_point, i, distance
    
    # If no lines within search distance, return nothing
    else:
        return None, None, None

def list_sindex(geometries):
    """Create a spatial index for a list of geometries.

    Parameters
    ----------
    geometries : :obj:`list`
        List of :class:`shapely.geometry.Point`,\
        :class:`shapely.geometry.MultiPoint`,\
        :class:`shapely.geometry.LineString`,\
        :class:`shapely.geometry.MultiLineString`,\
        :class:`shapely.geometry.Polygon`,\
        :class:`shapely.geometry.MultiPolygon` or\
        :class:`shapely.geometry.collection.GeometryCollection`

    Returns
    ----------
    :class:`rtree.index.Index`
        Spatial index
    """
    idx = index.Index()
    for i, geom in enumerate(geometries):
        idx.insert(i, geom.bounds, obj=i)
    return idx


def spaced_points_along_line(linestring, spacing, centered = False):
    """Create equally spaced points along a Shapely LineString.

    If a list of LineStrings is entered, the function will construct points
    along each LineString but will return all points together in the same
    list.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString` or :obj:`list`
        If list, must contain only :class:`shapely.geometry.LineString` objects.
    spacing : :obj:`float`
        Spacing for points along the `linestring`.
    centered : :obj:`bool` or :obj:`str`, optional, default = ``False``
        * ``False``: Points/Spaces aligned with the start of the `linestring`.
        * ``'Point'``: Points aligned with the midpoint of the `linestring`.
        * ``'Space'``: Spaces aligned with the midpoint of the `linestring`.

    Returns
    ----------
    :obj:`list`
        List of :class:`shapely.geometry.Point` objects.
    """
    if isinstance(linestring, LineString):
        linestring = [linestring] # If only one LineString, make into list
    all_points = []
    for l, line in enumerate(linestring):
        points = []
        length = line.length
        for p in range(int(ceil(length/spacing))):
            if centered == False:
                starting_point = 0
            elif centered in ['point', True]:
                half_length = length / 2
                starting_point = (
                    half_length - ((half_length // spacing) * spacing))
            elif centered == 'space':
                # Space the starting point from the end so the points are
                # centered on the edge
                starting_point = (length - (length // spacing) * spacing) / 2
            x, y = line.interpolate(starting_point + (p * spacing)).xy
            point = sh.geometry.Point(x[0], y[0])
            # Store point in list
            points.append(point)
        all_points.extend(points)
    return all_points


def azimuth(linestring, degrees=True):
    """Calculate azimuth between endpoints of a LineString.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        Azimuth will be calculated between ``linestring`` endpoints.

    degrees : :obj:`bool`, optional, default = ``True``
        * ``True`` for azimuth in degrees.
        * ``False`` for azimuth in radians.

    Returns
    ----------
    :obj:`float`
        Azimuth between the endpoints of the ``linestring``.
    """ 
    u = endpoints(linestring)[0]
    v = endpoints(linestring)[1]
    azimuth = np.arctan2(u.y - v.y, u.x - v.x)
    if degrees:
        return np.degrees(azimuth)
    else:
        return azimuth


def split_line_at_vertices(linestring):
    """Split a LineString into segments at each of its vertices.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString to split into segments

    Returns
    ----------
    :obj:`list`
        Contains a :class:`shapely.geometry.LineString` for each segment
    """
    coords = list(linestring.coords)
    n_lines = len(coords) - 1
    return [LineString([coords[i],coords[i + 1]]) for i in range(n_lines)]


def endpoints(linestring):
    """Get endpoints of a LineString.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString from which to extract endpoints

    Returns
    ----------
    u : :class:`shapely.geometry.Point`
        Start point
    v : :class:`shapely.geometry.Point`
        End point
    """
    u = Point(linestring.xy[0][0], linestring.xy[1][0])
    v = Point(linestring.xy[0][-1], linestring.xy[1][-1])
    return u, v 


def azimuth_at_distance(linestring, distance, degrees=True):
    """Get the azimuth of a LineString at a certain distance along it.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString along which an azimuth will be calculated.
    distance : :obj:`float`
        Distance along `linestring` at which to calculate azimuth
    degrees: :obj:`bool`, optional, default = ``False``
        * ``True`` : Azimuth calculated in degrees
        * ``False`` : Azimuth calcualted in radians

    Returns
    -------
    :obj:`float`
        Azimuth of `linestring` at specified `distance`
    """
    segments = split_line_at_vertices(linestring)
    segment_lengths = [edge.length for edge in segments]
    cumulative_lengths = []
    for i, length in enumerate(segment_lengths):
        if i == 0:
            cumulative_lengths.append(length)
        else:
            cumulative_lengths.append(length + cumulative_lengths[i-1])
    # Get index of split edge that includes the specified distance by
    # searching the list in reverse order
    for i, length in reversed(list(enumerate(cumulative_lengths))):
        if length >= distance:
            segment_ID = i
    return azimuth(segments[segment_ID], degrees=degrees)          


def line_by_azimuth(start_point, length, azimuth, degrees=True):
    """Construct a LineString axd on a start point, length, and azimuth.

    Parameters
    ----------
    start_point : :class:`shapely.geometry.Point`
        Line start point
    length : :obj:`float`
        Line length
    azimuth : :obj:`float`
        Line aximuth
    degrees : :obj:`bool`, optional, default = ``True``
        * ``True`` : Azimuth specified in degrees
        * ``False`` : Azimuth specified in radians

    Returns
    -------
    :class:`shapely.geometry.LineString`
        Constructed LineString
    """
    if degrees:
        azimuth = np.radians(azimuth)
    vx = start_point.x + np.cos(azimuth) * length
    vy = start_point.y + np.sin(azimuth) * length
    u = Point([start_point.x, start_point.y])
    v = Point([vx, vy])
    return LineString([u, v])


def midpoint(linestring):
    """Get the midpoint of a LineString.

    Parameters
    ----------
    linestring : :class:`shapely.geometry.LineString`
        LineString along which to identify midpoint

    Returns
    -------
    :class:`shapely.geometry.Point`
        Midpoint of `linestring`
    """
    return linestring.interpolate(linestring.length / 2)


def gdf_split_lines(gdf, segment_length, centered = False, min_length = 0):
    """Split LineStrings in a GeoDataFrame into equal-length peices.

    Attributes in accompanying columns are copied to all children of each
    parent record.

    Parameters
    ----------
    gdf : :class:`geopandas.GeoDataFrame`
        Geometry type must be :class:`shapely.geometry.LineString`
    segment_length: :obj:`float`
        Length of segments to create.
    centered : :obj:`bool` or :obj:`str`, optional, default = ``False``
        * ``False`` : Not centered; points are spaced evenly from the start of each LineString 
        * ``'Point'`` : A point is located at each LineString midpoint
        * ``'Space'`` : A gap between points is centered on each LinesString

    Returns
    -------
    :class:`geopandas.GeoDataFrame`
    """
    # initiate new dataframe to hold segments
    segments = gpd.GeoDataFrame(data=None, columns=gdf.columns, 
                                geometry = 'geometry', crs=gdf.crs)
    for i, segment in gdf.iterrows():
        points = spaced_points_along_line(segment['geometry'], 
                                          segment_length, 
                                          centered = centered)
        points = points[1:] # exclude the starting point
        # cut the segment at each point
        segment_geometries = split_line_at_points(segment['geometry'], points)
        if len(segment_geometries) > 1:
            # merge the end segments less than minimum length
            if segment_geometries[0].length < min_length:
                print(len(segment_geometries))
                segment_geometries[1] = linemerge(MultiLineString(
                    [segment_geometries[0], segment_geometries[1]]))
                segment_geometries = segment_geometries[1:]
            if segment_geometries[-1].length < min_length:
                segment_geometries[-2] = linemerge(MultiLineString(
                    [segment_geometries[-2], segment_geometries[-1]]))
                segment_geometries = segment_geometries[:-1]
        # copy the segment records
        segment_records = gpd.GeoDataFrame(
            data=[segment]*len(segment_geometries), columns=gdf.columns, 
            geometry = 'geometry', crs=gdf.crs)
        # replace the geometry for these copied records with the segment geometry
        segment_records['geometry'] = segment_geometries
        # add new segments to full list
        segments = segments.append(segment_records, ignore_index=True)
    return segments


def gdf_bbox(gdf):
    """Make a bounding box around all geometries in a GeoDataFrame.

    Parameters
    ----------
    gdf : :class:`geopandas.GeoDataFrame`
        GeoDataFrame with geometries around which to define bounding box

    Returns
    -------
    :class:`geopandas.Polygon`
        Bounding box
    """
    bounds = gdf.total_bounds
    return Polygon([(bounds[0], bounds[1]),
                    (bounds[2], bounds[1]),
                    (bounds[2], bounds[3]),
                    (bounds[0], bounds[3])])


def gdf_centroid(gdf):
    """Replace GeoDataFrame geometries with centroids.

    Parameters
    ----------
    gdf : :class:`geopandas.GeoDataFrame`
        GeoDataFrame with LineString or Polygon geometries

    Returns
    -------
    :class:`geopandas.GeoDataFrame`
        GeoDataFrame with original geometies replaced by their centroids
    """
    gdf = gdf.copy()
    centroids = gdf.centroid
    gdf['geometry'] = centroids
    return gdf 


def haversine(lon1, lat1, lon2, lat2, unit = 'km'):
    """Calculate the great circle distance between two lat/lons.

    Adapted from https://stackoverflow.com/questions/4913349

    Parameters
    ----------
    lon1 : :obj:`float`
        Longitude of 1st point
    lat1 : :obj:`float`
        Latitute of 1st point
    lon2 : :obj:`float`
        Longitude of 2nd point
    lat2 : :obj:`float`
        Latitude of 2nd point
    unit : :obj:`str`, optional, default = ``'km'``
        * ``'km'`` : Kilometers
        * ``'mi'`` : Miles

    Returns
    -------
    :obj:`float`
        Distance in specified unit
    """
    if unit == 'km':
        r = 6371 # Radius of the earth in km
    elif unit == 'mi':
        r = 3956 # Radius of the earth in mi
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return c * r


def degrees_centered_at_zero(degrees):
    """Rescale degrees so they are centered at 0.

    Ouputs will range from -180 to 180.
    
    Parameters
    ----------
    degrees : :obj:`float`
        Degrees centered at 180 (e.g., ranging from 0 to 360)

    Returns
    -------
    :obj:`float`
        Degrees centered at 0
    """
    if degrees > 180:
        degrees = degrees - 360
    elif degrees < -180:
        degrees = degrees + 360
    elif degrees == -180:
        degrees = 180
    return degrees



def side_by_relative_angle(angle):
    """Assign side axd on relative angle centered on 0 degrees.

    Negative angles are left. Positive angles are right.
    
    Parameters
    ----------
    degrees : :obj:`float`
        Degrees centered at 180 (e.g., ranging from 0 to 360)

    Returns
    -------
    :obj:`str`
        * ``'L'`` : Left
        * ``'R'`` : Right
        * ``'C'`` : Centered
    """
    if angle < 0:
        return 'R'
    elif angle > 0:
        return 'L'
    else:
        return 'C'

 
def float_overlap(min_a, max_a, min_b, max_b):
    """Get the overlap between two floating point ranges.

    Adapted from https://stackoverflow.com/questions/2953967/built-in-function-for-computing-overlap-in-python

    Parameters
    ----------
    min_a : :obj:`float`
        First range's minimum
    max_a : :obj:`float`
        First range's maximum
    min_b : :obj:`float`
        Second range's minimum
    max_b : :obj:`float`
        Second range's maximum

    Returns
    -------
    :obj:`float`
        Length of overlap between ranges
    """
    return max(0, min(max_a, max_b) - max(min_a, min_b))


def clip_line_by_polygon(line, polygon):
    """Clip a polyline to the portion within a polygon boundary.
    
    Parameters
    ----------
    line : :class:`shapely.geometry.LineString`
        Line to clip
    polygon : :class:`shapely.geometry.Polygon`
        Polygon to clip by

    Returns
    -------
    :class:`shapely.geometry.LineString` or :class:`shapely.geometry.MultiLineString`
        Line segment(s) within the polygon boundary
    """
    if line.intersects(polygon.boundary):
        split_lines = split_line_at_intersection(line, polygon.boundary)
        within_lines = []
        for line in split_lines:
            if shorten_line(line, 1e-6).within(polygon):
                within_lines.append(line)
        if len(within_lines) == 1:
            return within_lines[0]
        else:
            return MultiLineString(within_lines)
    elif shorten_line(line, 1e-6).within(polygon):
        return line
    else:
        return None


def gdf_clip_line_by_polygon(line_gdf, polygon_gdf):
    """Clip a polyline to the portion within a polygon boundary.
    
    Parameters
    ----------
    line_gdf : :class:`geopandas.GeoDataFrame`
        Lines to clip. Geometry type must be :class:`shapely.geometry.LineString`
    polygon_gdf : :class:`geopandas.GeoDataFrame`
        Polygons to clip by. Geometry type must be :class:`shapely.geometry.Polygon`
    Returns
    -------
    :class:`geopandas.GeoDataFrame`
        Line segments within the polygons
    """
    line_gdf = line_gdf.copy()
    line_gdf['line_index'] = line_gdf.index
    line_columns = list(line_gdf.columns)
    line_columns.remove('geometry')
    polygon_gdf = polygon_gdf.copy()
    polygon_gdf['polygon_index'] = polygon_gdf.index
    polygon_columns = list(polygon_gdf.columns)
    polygon_columns.remove('geometry')
    output_columns = line_columns + polygon_columns + ['geometry']
    clip_gdf = gpd.GeoDataFrame(columns=output_columns, geometry='geometry', crs=line_gdf.crs)
    for polygon in polygon_gdf.itertuples():
        for line in line_gdf.itertuples():
            clipped = clip_line_by_polygon(line.geometry, polygon.geometry)
            if clipped is not None:
                polygon_dict = polygon._asdict()
                for x in ['geometry', 'Index']:
                    polygon_dict.pop(x, None)
                line_dict = line._asdict()
                for x in ['geometry', 'Index']:
                    line_dict.pop(x, None)
                new_dict = {**line_dict, **polygon_dict}
                if isinstance(clipped, LineString):
                    new_dict['geometry'] = clipped
                    new_gdf_row = gpd.GeoDataFrame([new_dict], geometry='geometry', crs=line_gdf.crs)
                    clip_gdf = pd.concat([clip_gdf, new_gdf_row])
                elif isinstance(clipped, MultiLineString):
                    for line in clipped:
                        new_dict['geometry'] = line
                        new_gdf_row = gpd.GeoDataFrame([new_dict], geometry='geometry', crs=line_gdf.crs)
                        clip_gdf = pd.concat([clip_gdf, new_gdf_row])
    clip_gdf = df_first_column(clip_gdf, 'line_index')
    clip_gdf = df_first_column(clip_gdf, 'polygon_index')
    clip_gdf = df_last_column(clip_gdf, 'geometry')
    return clip_gdf


def lines_polygons_intersection(lines, polygons, polygons_sindex=None, singlepart=False):
    """Finds intersection of all lines with all polygons.
    
    Parameters
    ----------
    lines : LineString or MultiLineString GeoDataFrame
    polygons : Polygon GeoDataFram
    polygons_sindex : Spatial index for polygons

    Returns
    -------
    LineString or MultiLineString GeoDataFrame
    """
    # Create a spatial index for polygons if not supplied
    if polygons_sindex is None:
        polygons_sindex = polygons.sindex
    # Initiate a new geodataframe to store results
    results = GeoDataFrame(columns = ['polygon_id'] + list(lines.columns))
    # Iterate through lines
    for line in lines.itertuples():
        # Convert line record to a mutable dictionary
        possible_matches = polygons.iloc[list(
            polygons_sindex.intersection(line.geometry.bounds))]
        for polygon in possible_matches.itertuples():
            # print(polygon)
            intersection = line.geometry.intersection(polygon.geometry)
            if isinstance(intersection, (LineString, MultiLineString)):
                # If input was MultiLineString, keep as MultiLineString
                if (type(lines.geometry[0]) == MultiLineString) and not singlepart:
                    # And intersection is only LineString
                    if isinstance(intersection, LineString):
                        # Convert to MultiLineString
                        instersection = MultiLineString([intersection])
                # If explicitly singlepart, convert MultiLineStrings to LineStrings
                if singlepart:
                    if isinstance(intersection, MultiLineString):
                        intersection = [x for x in intersection]
                # Make intersection into a list if not already
                intersection = listify(intersection)
                # Add row to results for each element in intersection
                for x in intersection:
                    # Make a copy of the row
                    result_line = line._asdict()
                    # Replace its geometry with the intersection
                    result_line['geometry'] = x
                    # Add a field for the polygon id
                    result_line['polygon_id'] = polygon.Index
                    # Rename line id field
                    result_line['line_id'] = line.Index
                    result_line.pop('Index')
                    # Append it to the results
                    results = results.append(result_line, ignore_index=True)

    # Ensure that indices are stored as integers
    results['line_id'] = pd.Series(results['line_id'], dtype='int32')
    results['polygon_id'] = pd.Series(results['polygon_id'], dtype='int32')
    # Rearrange columns
    results = df_first_column(results, 'polygon_id')
    results = df_first_column(results, 'line_id')
    results = df_last_column(results, 'geometry')
    return results


def lines_polygons_difference(lines, polygons, polygons_sindex=None):
    """Finds intersection of all lines with all polygons.
    
    Parameters
    ----------
    lines : LineString or MultiLineString GeoDataFrame
    polygons : Polygon GeoDataFram
    polygons_sindex : Spatial index for polygons

    Returns
    -------
    LineString or MultiLineString GeoDataFrame
    """
    # Create a spatial index for polygons if not supplied
    if polygons_sindex is None:
        polygons_sindex = polygons.sindex
    # Initiate a new geodataframe to store results
    results = GeoDataFrame(columns = ['polygon_id'] + list(lines.columns))
    # Iterate through lines
    for line in lines.itertuples():
        # Convert line record to a mutable dictionary
        possible_matches = polygons.iloc[list(
            polygons_sindex.intersection(line.geometry.bounds))]
        for polygon in possible_matches.itertuples():
            # print(polygon)
            intersection = line.geometry.difference(polygon.geometry)
            if isinstance(intersection, (LineString, MultiLineString)):
                # If input was MultiLineString
                if type(lines.geometry[0]) == MultiLineString:
                    # And intersection is only LineString
                    if isinstance(intersection, LineString):
                        # Convert to MultiLineString
                        instersection = MultiLineString([intersection])
                # Make a copy of the row
                result_line = line._asdict()
                # Replace its geometry with the intersection
                result_line['geometry'] = intersection
                # Add a field for the polygon id
                result_line['polygon_id'] = polygon.t
                # Rename line id field
                result_line['line_id'] = line.Index
                result_line.pop('Index')
                # Append it to the results
                results = results.append(result_line, ignore_index=True)
    # Ensure that indices are stored as integers
    results['line_id'] = pd.Series(results['line_id'], dtype='int32')
    results['polygon_id'] = pd.Series(results['polygon_id'], dtype='int32')
    # Rearrange columns
    results = df_first_column(results, 'polygon_id')
    results = df_first_column(results, 'line_id')
    results = df_last_column(results, 'geometry')
    return results
    

def shape_to_gdf(shape, crs=None):
    """Convert one or more shapes to a geodataframe.

    Parameters
    ----------
    shape : list or Shapely geometry
        List of geometries to be converted into a geodataframe. If a single\
        geometry, the returned geodataframe will have one row.

    Returns
    -------
    :class:`geopandas.GeoDataFrame`
        Geodataframe with geometries in the 'geometry' column.
    """
    # if just one shape, put it in a list
    if isinstance(shape, (Point, MultiPoint, LineString, MultiLineString, 
                          Polygon, MultiPolygon)):
        shape = [shape]
    return gpd.GeoDataFrame(geometry=shape, crs=crs)

def label_features(axis, gdf, label_column, offset, **kwargs):
    """Label features plotted from a geodataframe.

    """
    
    # shift midpoint randomly +/- 25% of edge length
    def get_label_point(feature, jitter = None):
        """Calculate point for labeling a feature

        ``jitter`` is the proportion of a feature's extent within which to randomly
        jitter label position relative to the feature's centroid of midpoint.

        """
        if isinstance(feature, LineString):
            mid_dist = feature.length / 2
            if jitter:
                jitter_range = feature.length * jitter
                mid_dist = mid_dist + random.uniform(-jitter_range, jitter_range)
            return feature.interpolate(mid_dist)

        else:
            label_point = feature.centroid
            if jitter:
                minx, miny, maxx, maxy = feature.bounds
                jitter_range = max([(maxx-minx),(maxy-miny)]) * jitter
                x = label_point.x + random.uniform(-jitter_range, jitter_range)
                y = label_point.y + random.uniform(-jitter_range, jitter_range)
            return Point(x,y)

    gdf.apply(lambda edge: axis.annotate(s=edge[label_column], 
        xy=(get_label_point(edge.geometry, jitter = None).x + offset[0], 
            get_label_point(edge.geometry, jitter = None).y + offset[1]), 
        **kwargs), axis=1)

def plot_shapes(shapes, ax=None, axis_off=True, size=8, extent=None, 
    legend=None, leaflet=False):
    """Plot multiple shapes.

    Parameters
    ----------
    shapes : list or Shapely geometry
        * a single geometry will be plotted by itself
        * each geometry in a list will be plotted in a seperate color
        * tuples like (geom, {'color':'color'}) may be passed to specify colors\
        and other attributes
        * default color order is: brgcmyk
        * colors will be repeated as necessary

    ax : predifined axis object, optional, default = ``None``
        If specified, shapes will be plotted on this axis

    axis_off : :obj:`bool`, optional, default = ``False``
        * ``True`` : plot will omit axis markings
        * ``False`` : plot will include axis markings

    size : :obj:`int`, optional, default = ``8``
        Square size of returned plot (used for both length and width)

    extent : :obj:`tuple`, optional, default = ``None``
        * (minx, miny, maxx, maxy)
        * If specified, restricts axis to specific extent.

    legend : :obj:`list`, optional, default = ``None``
        List with the same length and order as ``shapes``

    leaflet : :obj:`bool`, optional, default = ``False``
        * ``True`` : will plot in leaflet in a new browser window
        * ``False`` : will plot normally in-line
    """

    # Make sure shapes are in a list
    shapes = listify(shapes)

    # Turn all individual shapes and lists of shapes into geodataframes
    attribute_dicts = [None] * len(shapes)
    for i, shape in enumerate(shapes):
        # If shapes are specified as tuples with attributes, break out attributes
        if isinstance(shape, tuple):
            shape, attribute_dicts[i] = shape
        # If individual shape, make into sublist
        if isinstance(shape, (Point, MultiPoint, LineString, 
                              MultiLineString, Polygon, MultiPolygon)):
            shape = [shape]
        # If list, make into geodataframe
        if isinstance(shape, list):
            shape = shape_to_gdf(shape)
        # Save manipulated shape back to shapes list
        shapes[i] = shape
   
    # Collect each attribute
    colors = [None] * len(shapes)
    alphas = [1] * len(shapes)
    labels = [None] * len(shapes)
    legend_entries = [None] * len(shapes)

    if any(attribute_dicts):
        for i, attribute_dict in enumerate(attribute_dicts):
            if attribute_dict:
                if 'color' in attribute_dict:
                    colors[i] = attribute_dict['color']
                if 'alpha' in attribute_dict:
                    alphas[i] = attribute_dict['alpha']   
                if 'label' in attribute_dict:
                    labels[i] = attribute_dict['label']
                if 'legend' in attribute_dict:
                    legend_entries[i] = attribute_dict['legend']
   
    # Combine default and custom colors
    default_colors = cycle(list('brgcmyk'))
    colors = [color if color else next(default_colors) for 
              color in colors]
   
    # Reverse the lists so the first one draws last
    shapes = list(reversed(shapes))
    colors = list(reversed(colors))
    alphas = list(reversed(alphas))
    labels = list(reversed(labels))
       
    # If labeling, compute maximum extent to enable label placement
    if any(labels):
        bboxes = []
        for i, shape in enumerate(shapes):
            bboxes.append(sh.geometry.box(*tuple(shape.total_bounds)))
        minx, miny, maxx, maxy = shape_to_gdf(bboxes).total_bounds
        max_extent = max([(maxx-minx),(maxy-miny)])
        offset = max_extent / 120

    # Plot the first shape
    if not ax:
        if not isinstance(size, tuple):
            size = (size, size)
        fig, ax = plt.subplots(1, figsize=size)
    first_shape = shapes[0]
    first_shape.plot(ax=ax, color=colors[0], alpha=alphas[0])
    if labels[0]:
        if not labels[0] in first_shape.columns:
            first_shape[labels[0]] = labels[0]
        label_features(
            ax, first_shape, labels[0], (offset,offset), color=colors[0], ha='left')

    # plot remaining shapes
    if len(shapes) > 0:
        remaining_shapes = shapes[1:]
        for i, shape in enumerate(remaining_shapes):
            shape.plot(ax=ax, color=colors[i+1], alpha=alphas[i+1])
            if labels[i+1]:
                if not labels[i+1] in shape.columns:
                    shape[labels[i+1]] = labels[i+1]
                label_features(
                    ax, shape, labels[i+1], (offset,offset), color=colors[i+1], ha='left')
    
    if leaflet:
        mplleaflet.show(fig=fig, crs=shapes[0].crs, tiles='cartodb_positron')
    
    else:
        if extent:
            ax.axis('equal')
            minx, miny, maxx, maxy = extent
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
            if axis_off:
                ax.set_xticklabels([])
                ax.set_yticklabels([])
                ax.set_xticks([])
                ax.set_yticks([])
        
        else:
            ax.axis('equal')
            if axis_off:
                ax.axis('off')

        if any(legend_entries):
            # Get list of layers
            layers = ax.collections
            # Reverse list
            layers = layers[::-1]

            # Keep only layers with non-None legend entries
            layers = [layer for layer, entry 
                      in zip(layers, legend_entries) if entry]

            # Keep only non-None legend entries
            legend_entries = [entry for entry in legend_entries if entry]
            
            # legend_handles, _ = ax.get_legend_handles_labels()
            ax.legend(layers, legend_entries)

    try:
        return fig, ax
    except:
        pass

def intersect_shapes(shapes_a, shapes_b, shapes_b_sindex=None):
    """Find intersections between shapes in two lists

    Parameters
    ----------
    shapes_a : list of Shapely geometries
        List of geometries to be intersected with those in shapes_b
    shapes_b : list of Shapely geometries
        List of geometries to be intersected with those in shapes_a
    shapes_b_sindex : :class:`rtree.index.Index`, optional, default = ``None``
        Spatial index for shapes_b (best created with ``list_sindex``)

    Returns
    -------
    :obj:`list`
        List of tuples for each intersection with structure:\
        (a_index, b_index, intersection_geometry)
    """
    intersections = []
    for i, shape_a in enumerate(shapes_a):
        indices_b = list(range(len(shapes_b)))
        if shapes_b_sindex:
            b_for_analysis = [(indices_b[i], shapes_b[i]) for i in 
                              shapes_b_sindex.intersection(shape_a.bounds)]#, objects='raw')]
        else:
            b_for_analysis = zip(indices_b, shapes_b)       
        for j, shape_b in b_for_analysis:
            if shape_a.intersects(shape_b):
                intersection = shape_a.intersection(shape_b)
                intersections.append((i, j, intersection))
    return intersections


def normalize_azimuth(azimuth, zero_center=False):
    """Normalize an azimuth in degrees so it falls between 0 and 360.
    
    If ``zero_center=True``, azimuth will be normalized
    between -180 and 180.
    """
    if (azimuth > 360 or azimuth < 0):
        azimuth %= 360
    if zero_center:
        if azimuth > 180:
            azimuth -= 360
    return azimuth      


def azimuth_difference(azimuth_a, azimuth_b, directional=True):
    """Find the difference between two azimuths specifed in degrees.
    
    If ``directional=False``, will also examine difference if one
    azimuth is rotated 180 degrees and will return the smaller
    of the two differences.   
    """
    azimuth_a = normalize_azimuth(azimuth_a, zero_center=True)
    azimuth_b = normalize_azimuth(azimuth_b, zero_center=True)
    def _diff(a, b):
        difference = a-b
        if difference > 180:
            difference -= 360
        if difference < -180:
            difference += 360
        return abs(difference)
    difference = _diff(azimuth_a, azimuth_b)   
    if not directional:
        rotated_difference = _diff(azimuth_a + 180, azimuth_b)
        difference = min([difference, rotated_difference])
    return difference


def closest_point_along_line(point, line):
    """Return the point along a line that is closest to another point.

    ``point`` must be a Shapely Point.

    ``line`` must be a Shapely LineString.
    """
    return line.interpolate(line.project(point))


def vertices_to_points(shape):
    """Return vertices of a shape as a list of points.

    ``shape`` must be a Shapely geometry. 
    """
    return [Point(coords) for coords in np.array(shape)]


def directed_hausdorff(a, b):
    """Calculate the directed Hausdorff distance from shape a to shape b.

    ``a`` and ``b`` must be Shapely geometries
    """
    a_nodes = vertices_to_points(a)
    b_match_points = [closest_point_along_line(node, b) for node in a_nodes]
    dists = [a_node.distance(b_point) for a_node, b_point in zip(a_nodes, b_match_points)]
    return max(dists)


def gdf_intersecting_polygon(gdf, polygon, gdf_sindex=None, quadrat_size=None):
    """

    """
    if not gdf_sindex:
        gdf_sindex = gdf.sindex
    if not quadrat_size:
        minx, miny, maxx, maxy = polygon.bounds
        max_dimension = max([maxx-minx, maxy-miny])
        quadrat_size = max_dimension / 10
    gdf['unique_identifier'] = gdf.index
    polygon_cut = ox.quadrat_cut_geometry(polygon, quadrat_width=2500)
    # Find the points that intersect with each subpolygon and add them to points_within_geometry
    selection = pd.DataFrame()
    for poly in polygon_cut:
        # Buffer by the <1 micron dist to account for any space lost in the quadrat cutting
        # otherwise may miss point(s) that lay directly on quadrat line
        poly = poly.buffer(1e-14).buffer(0)
        # Find approximate matches with r-tree, then precise matches from those approximate ones
        possible_matches_index = list(gdf_sindex.intersection(poly.bounds))
        possible_matches = gdf.iloc[possible_matches_index]
        precise_matches = possible_matches[possible_matches.intersects(poly)]
        selection = selection.append(precise_matches)
    # Drop duplicate rows intersecting with multiple polygons
    selection = selection.drop_duplicates(subset=['unique_identifier'])
    selection = selection.drop(columns=['unique_identifier'])
    return selection


def major_axis_azimuth(polygon):
    """Calculate the azimuth of a LineString's or Polygon's major axis

    """
    rectangle = polygon.minimum_rotated_rectangle
    if isinstance(rectangle, LineString):
        longest_sides = [rectangle]
    # elif isinstance(rectangle, Point):
    #     return 0
    else:
        try:
            sides = split_line_at_vertices(rectangle.boundary)
            lengths = [x.length for x in sides]
            longest_sides = [side for side, length 
                in zip(sides, lengths) if length == max(lengths)]
        except:
            print(type(polygon), polygon, type(rectangle), rectangle)
    azimuths = [azimuth(x) for x in longest_sides]    
    return max(azimuths)