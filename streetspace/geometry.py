"""Functions to manipulate Shapely geometries."""

##############################################################################
# Module: geometry.py
# Description: Functions to manipulate Shapely geometries.
# License: MIT
##############################################################################

import shapely as sh
import numpy as np
from shapely.ops import linemerge
from shapely.geometry import (Point, MultiPoint, LineString, MultiLineString,
    Polygon, MultiPolygon, GeometryCollection)
from math import radians, cos, sin, asin, sqrt, ceil
import geopandas as gpd
import pandas as pd
from rtree import index

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
    # sort the coords/cuts based on the distances
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


def closest_point_along_lines(search_point, linestrings, search_distance=None,
    linestrings_sindex=None):
    """Find the closest point along any of multiple LineStrings.

    TODO: Would it be easier for the input to this to be a geodataframe?
    That way the spatial index could be constructed inline, if necessary,
    as 'GeoDataFrame.sindex'.

    Parameters
    ----------
    search_point : :class:`shapely.geometry.Point`
        Point from which to search
    linestrings : :obj:`list` 
        LineStrings to search. Must contain :class:`shapely.geometry.LineString`
    search_distance : :obj:`float`, optional
        Distance to search from the `search_point`. If not specified,\
        LineStrings will be searched no matter their distance from the\
        `search_point`.
    linestrings_sindex : :class:`rtree.index.Index`, optional
        Spatial index for LineStrings in `linestrings`
    
    Returns
    -------
    :obj:`int`
        Index of the closest LineString
    :class:`shapely.geometry.Point`
        Closest Point along that LineString
    """
    # Get linestrings within the search distance based a specified spatial index:  
    if linestrings_sindex != None:
        if search_distance == None:
            raise ValueError('Must specify search_distance if using spatial index')
        # construct search area around point
        search_area = search_point.buffer(search_distance)
        # get nearby IDs
        find_line_indices = [int(i) for i in 
            linestrings_sindex.intersection(search_area.bounds)]
        # Get nearby geometries:
        linestrings = [linestrings[i] for i in find_line_indices]
    # Get linestrings within a specified search distance:
    elif search_distance != None:
        # construct search area around point
        search_area = search_point.buffer(search_distance)
        # get linestrings intersecting search area
        linestrings, find_line_indices = zip(*[(line, i) for i, line in 
                                             enumerate(linestrings) if
                                             line.intersects(search_area)])
    # Otherwise, get all linestrings:
    find_line_indices = [i for i, _ in enumerate(linestrings)]
    # Calculate distances to all remaining linestrings
    distances = []
    for line in linestrings:
        distances.append(search_point.distance(line))
    # Only return a closest point if there is a line within search distance:
    if len(distances) > 0:
        # find the line index with the minimum distance
        _, line_idx = min((distance, i) for (i, distance) in 
                              zip(find_line_indices, distances))
        # Find the nearest point along that line
        search_line = linestrings[find_line_indices.index(line_idx)]
        lin_ref = search_line.project(search_point)
        closest_point = search_line.interpolate(lin_ref)
        return line_idx, closest_point
    else:
        return None, None


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
        idx.insert(i, geom.bounds)
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
    """Construct a LineString based on a start point, length, and azimuth.

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
    """Assign side based on relative angle centered on 0 degrees.

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
    line_gdf['line_index'] = line_gdf.index
    line_columns = list(line_gdf.columns)
    line_columns.remove('geometry')
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
                    for line in MultiLineString:
                        new_dict['geometry'] = line
                        new_gdf_row = gpd.GeoDataFrame([new_dict], geometry='geometry', crs=line_gdf.crs)
                        clip_gdf = pd.concat([clip_gdf, new_gdf_row])
    clip_gdf = df_first_column(clip_gdf, 'line_index')
    clip_gdf = df_first_column(clip_gdf, 'polygon_index')
    clip_gdf = df_last_column(clip_gdf, 'geometry')
    return clip_gdf











