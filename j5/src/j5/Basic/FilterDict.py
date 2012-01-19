#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Component which represents a database table filter."""

import pytz
from j5.Database import Dates
from j5.OS import datetime_tz

from j5.Basic import DictUtils
import datetime
import base64
import logging
import json

class filterdict(DictUtils.attrdict):
    """A dictionary that holds filter options, and makes them available as attributes"""

def filtervalue_to_safe_str(value):
    """converts a filter value to a string that's safe to pass through URLs"""
    value_type = ""
    if isinstance(value, unicode):
        value_type = "u!"
        value = value.encode("UTF-8")
    elif isinstance(value, str):
        value_type = "s!"
    else:
        value = str(value)
    return value_type + base64.b32encode(value).replace("=",".")

def safe_str_to_filtervalue(value):
    """converts a URL-safe string back to a filter value"""
    value_type = str
    if value.startswith("s!"):
        value = value[2:]
    elif value.startswith("u!"):
        value_type = unicode
        value = value[2:]
    try:
        value = base64.b32decode(value.replace(".","="))
    except TypeError as e:
        raise TypeError("Error decoding b32: %s for %r" % (e, value))
    if value_type == unicode:
        value = value.decode("UTF-8")
    return value

def filterdict_to_str(fdict):
    """Convert a filter dictionary to a string which can be passed around URLs."""
    # Note: b32encode produces only [A-Za-z0-9_=]
    if fdict is None:
        return ""
    if not fdict:
        return "-"
    keystrs = []
    for key, values in fdict.items():
        keystrs.append(",".join([filtervalue_to_safe_str(value) for value in [key] + values]))
    return ":".join(keystrs)

def str_to_filterdict(s):
    """Convert a string generated by filterdict_to_str back to a filter dictionary."""
    if not s:
        return None
    if s == "-":
        return filterdict()
    keystrs = s.split(":")
    fdict = filterdict()
    for keystr in keystrs:
        try:
            items = [safe_str_to_filtervalue(x) for x in keystr.split(",")]
        except TypeError as e:
            logging.error("Error decoding base64-encoded filter %s: %s", keystr, e)
            raise TypeError("Error decoding base64-encoded filter %s: %s" % (keystr, e))
        fdict[items[0]] = items[1:]
    return fdict

def combine_filterdicts(first, second):
    if first is None:
        return second
    if second is None:
        return first
    combine = filterdict(first)
    for k, v in combine.iteritems():
        if not isinstance(v, (list, tuple)):
            combine[k] = [v]
    for key in second:
        if isinstance(second[key], (list, tuple)):
            secondval = second[key]
        else:
            secondval = [second[key]]
        if key not in combine:
            combine[key] = secondval
        else:
            combine[key] = list(set(combine[key]).union(secondval))
    return combine

def split_select_filter_value(field_value):
    """handles splitting a filter field value into multiple options separated by , if present"""
    incoming_field_value = field_value
    if field_value is None:
        field_value = []
    if isinstance(field_value, list) and len(field_value) == 1:
        field_value = field_value[0]
    if isinstance(field_value, basestring):
        field_value = [fv for fv in field_value.split(",")]
    field_value = [fv for fv in field_value if field_value]
    return field_value

def filterdict_to_json_str(filter_dict, **kwargs):
    json_map = {}
    for (field, val_list) in filter_dict.items():
        _convert_filter_dict_field(json_map, field, val_list)

    json_map = _flatten_json_map(json_map)

    return json.dumps(json_map, **kwargs)

def json_str_to_filterdict(json_str):
    json_map = json.loads(json_str)
    json_map = _expand_json_map(json_map)

    filter_dict = {}
    _convert_json_map_fields(filter_dict, '', json_map)

    return filter_dict

def _convert_filter_dict_field(target_map, field, val_list):
    first_slash = field.find("/")
    if first_slash >= 0:
        sub_log_name = "sublog.%s" % field[0:first_slash]
        if not sub_log_name in target_map:
            target_map[sub_log_name] = {}
        sub_fieldname = field[first_slash+1:]
        _convert_filter_dict_field(target_map[sub_log_name], sub_fieldname, val_list)
    else:
        n_list = []
        for v in val_list:
            if isinstance(v, datetime.datetime):
                if not v.tzinfo:
                    v = datetime_tz.localize(v)
                elif not isinstance(v, datetime_tz.datetime_tz):
                    v = datetime_tz.datetime_tz(v)
                tz = str(v.tzinfo)
                date_str = v.astimezone(pytz.UTC).isoformat()

                v = {"datetime" : date_str, "tz" : tz}
            n_list.append(v)

        last_dot = field.rfind(".")
        if last_dot >= 0:
            sub_fieldname = field[last_dot+1:]
            field_name = field[0:last_dot]
        else:
            sub_fieldname = "match"
            field_name = field

        if not field_name in target_map:
            target_map[field_name] = {}

        if len(n_list) == 1:
            target_map[field_name][sub_fieldname] = n_list[0]
        else:
            target_map[field_name][sub_fieldname] = n_list

def _convert_json_map_fields(filter_dict, prefix, json_map):
    for (k,v) in json_map.items():
        if k.startswith("sublog."):
            _convert_json_map_fields(filter_dict, k[len("sublog."):]+'/', v)
        else:
            for (sub_fieldname,subv) in v.items():
                subv = [_convert_datetimes_from_json(v) for v in subv]
                if (sub_fieldname == "match"):
                    filter_dict[prefix+k] = subv
                else:
                    filter_dict[prefix+k+"."+sub_fieldname] = subv

def _convert_datetimes_from_json(v):
    if isinstance(v, dict):
        dt = Dates.parse_dojo_date(v["datetime"])
        if not isinstance(v, datetime_tz.datetime_tz):
            dt = datetime_tz.datetime_tz(dt)
        tz = v.get("tz", None)
        if  tz:
            dt = dt.astimezone(pytz.timezone(str(tz)))
        return dt
    else:
        return v

def _flatten_json_map(json_map):
    n_map = {}
    for (k,v) in json_map.items():
        if k.startswith("sublog."):
            v = _flatten_json_map(v)
        else:
            nv = {}
            for (sk,l) in v.items():
                if isinstance(l, list) and len(l) == 1:
                    nv[sk] = l[0]
                else:
                    nv[sk] = l
            v = nv

            if (len(v) == 1 and "match" in v):
                v = v["match"]

        n_map[k] = v
    return n_map

def _expand_json_map(json_map):
    n_map = {}
    for (k,v) in json_map.items():
        if k.startswith("sublog."):
            v = _expand_json_map(v)
        else:

            if (not isinstance(v, dict) or (len(v)==1 and "datetime" in v) or (len(v)==2 and "datetime" in v and "tz" in v)):

                v = { "match" : v }

            nv = {}
            for (sk,l) in v.items():
                if not isinstance(l, list):
                    nv[sk] = [l]
                else:
                    nv[sk] = l
            v = nv

        n_map[k] = v
    return n_map
