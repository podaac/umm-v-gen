#!/usr/bin/env python3
import re
import sys
import json
import requests
import xml.etree.ElementTree as etree
from os.path import realpath, abspath, dirname, isfile, join
from json.decoder import JSONDecodeError
from argparse import ArgumentParser
from netCDF4 import Dataset, numpy

_cmr = "cmr.earthdata.nasa.gov"

def _read_lptoken(cert: str="/launchpad_token_ngap_ops.json", **kwargs) -> str:
    if not isfile(cert):
        cert = "/home/podaacdev/certs/launchpad_token_ngap_ops.json"
        if not isfile(cert):
            raise Exception("A launchpad token is not available to the script!")
    if 'environment' in kwargs:
        cert = cert.replace("ops.json", f"{kwargs.get('environment')}.json")
    with open(cert, "r") as f:
        text = f.read()
        try:
            data = json.loads(text)
        except json.decoder.JSONDecodeError as e:
            text = "\n".join([l for l in text.split("\n") if '":,' not in l.replace(" ","")])
            try:
                data = json.loads(text)
            except json.decoder.JSONDecodeError as e:
                raise e
    return data.get("token")

#https://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml
_cf_names = join(abspath(dirname(realpath(__file__))), "resources/cf-standard-name-table.xml")

def _read_cfnames(xml: str=_cf_names):
    cf_standard_names = dict()
    try:
        with open(xml, "r", encoding="utf8") as f:
            xml = etree.fromstring(f.read())  #xml = f.read()
    except FileNotFoundError as e:
        raise e
    else:
        for n in xml.findall("entry"):
            cf_standard_names[n.items()[0][1]] = dict()
            for t in n.findall("*"):
                cf_standard_names[t.tag] = str(t.text)
    return cf_standard_names


_umm_var = "https://cdn.earthdata.nasa.gov/umm/variable/v1.8.1"

def _read_schema(url: str=f"{_umm_var}/umm-var-json-schema.json"):
    try:
        with requests.get(url) as response:
            return response.json()
    except JSONDecodeError as e:
        raise e


def convert(o):
    """Encode manually if np type doesn't serialize to JSON."""
    if isinstance(o, numpy.ndarray):
        return o.tolist()
    elif isinstance(o, str):
        return o.replace('"', "'")  # Replace escaped quotes in strings.
    elif isinstance(o, numpy.generic):
        if o.__class__.__name__.startswith("float"):
            return float(str(o))  # Protect against float precision errors
        return o.item()
    else:
        return o


def _txt_sanitize(d):
    if type(d) is numpy.ndarray:
        return " ".join(d.astype(str))
    elif type(d) is list:
        return " ".join([str(i) for i in d])
    else:
        return str(d)


_num_sanitize = re.compile(r'[^\d.-]+')

__datatypes__  = {
    #'S1' : 'NC_CHAR',    # char - Characters  # NOTE: Map NC_CHAR to 'string'
    'S1' : 'NC_STRING',  # ...data type in UMM-Var. See schema version 1.8.1
    'i1' : 'NC_BYTE',    # byte - Eight-bit integers
    'u1' : 'NC_UBYTE',   # ubyte - Unsigned eight-bit integers
    'i2' : 'NC_SHORT',   # short - 16-bit signed integers
    'u2' : 'NC_USHORT',  # ushort - Unsigned 16-bit integers
    'i4' : 'NC_INT',     # int - 32-bit signed integers
    'u4' : 'NC_UINT',    # uint - Unsigned 32-bit integers
    'i8' : 'NC_INT64',   # int64 - 64-bit signed integers
    'u8' : 'NC_UINT64',  # uint64 - Unsigned 64-bit signed integers
    'f4' : 'NC_FLOAT',   # float - IEEE single-precision float (32 bits)
    'f8' : 'NC_DOUBLE',  # double - IEEE double-precision float (64 bits)
    # Kludges to work around emerging blockers & edge cases ->
    "<class 'netCDF4._netCDF4.VLType'>: string type": "NC_STRING",  # VLType
    # Kludges to map compound types to umm types for RSCAT V2.0 (2023-05-10) ->
    "<class 'netCDF4._netCDF4.CompoundType'>:": "NC_UBYTE",
}


class Variable:
    schema = _read_schema()
    cfnames = _read_cfnames()

    def _Name(ncvar):
        """Name is the full path to the variable in the file. But variables 
        at the dataset root should not have a leading forward-slash '/'"""
        p = ncvar.group().path.replace(" ","_")
        return ncvar.name if p=="/" else f"{p}/{ncvar.name}"

    def _StandardName(ncvar):
        """StandardName is the 'standard_name' attribute of the variable, if 
        it exists."""
        if hasattr(ncvar, "standard_name"):
            return ncvar.standard_name

    def _AdditionalIdentifiers(ncvar):
        """AdditionalIdentifiers can be any information that doesn't have a 
        place elsewhere in the UMM Variable format, but that we want/need
        to report *consistently* within a UMM Variable record.

        The script is currently inserting an attribute called 
        'CF_Standard_Description' for any variable that has a 'standard_name' 
        with a corresponding description in the CF Standard Names table for 
        version xx (default: 76)
        """
        ai = []
        try:
            # Try to identify CF standard attributes for flags:
            if hasattr(ncvar, "flag_values"):
                ai.append({'Identifier': "CF_Flag_Values",
                           'Description': _txt_sanitize(ncvar.flag_values)})
            if hasattr(ncvar, "flag_meanings"):
                ai.append({'Identifier': "CF_Flag_Meanings",
                           'Description': _txt_sanitize(ncvar.flag_meanings)})
            if hasattr(ncvar, "flag_masks"):
                ai.append({'Identifier': "CF_Flag_Masks",
                           'Description': _txt_sanitize(ncvar.flag_masks)})
        except Exception as e:
            pass
        if hasattr(ncvar, "standard_name"):
            cfname = ncvar.standard_name 
            try:
                desc = Variable.cfnames[cfname]['description']
                if desc is not None:
                    ai.append({"Identifier": "CF_Standard_Description", 
                               "Description": desc})
            except (AttributeError, KeyError) as e:
                pass
        return None if len(ai)==0 else ai

    def _LongName(ncvar):
        """LongName comes from the variable 'long_name' attribute.

        Revisions:
          - 20210913: 'LongName' is a required field. Use 'Name' as fallback.
        
        """
        if hasattr(ncvar, "long_name"):
            return ncvar.long_name
        else:
            return Variable._Name(ncvar)

    def _Definition(ncvar):
        """Fall back on variable 'long_name'; otherwise use its name"""
        for attribute in ['description', 'comment', 'long_name', ]:
            if hasattr(ncvar, attribute):
                return getattr(ncvar, attribute)
        return str(ncvar.name)

    def _Units(ncvar):
        if hasattr(ncvar, "units"):
            return ncvar.units

    def _DataType(ncvar):
        """unidata.ucar.edu/software/netcdf/docs/netcdf_utilities_guide.html"""
        try:
            dtype_str = ncvar.datatype.str[1:]
        except AttributeError as e:
            #return __datatypes__[ncvar.datatype.__str__()]
            for type_name, type_code in __datatypes__.items():
                if str(ncvar.datatype).startswith(type_name):
                    return type_code[3:].lower()
        else:
            try:
                # Select and return UMM-compatible datatype string from dict
                return __datatypes__[dtype_str][3:].lower()
            except KeyError as e:
                raise e  # Occurs when no matching datatype string in dict
            except IndexError as e:
                raise e  # Occurs when datatype string does not exist
            except Exception as e:
                raise e  # Raised when uncovered bug occurs
        

    def _Dimensions(ncvar):
        def _predict_dim_type(dim):
            """Unused: (PRESSURE_DIMENSION,HEIGHT_DIMENSION,DEPTH_DIMENSION)"""
            name = dim.name.lower()
            if name=="time":
                _type = "TIME_DIMENSION"
            elif name.startswith("lat"):
                _type = "LATITUDE_DIMENSION"
            elif name.startswith("lon"):
                _type = "LONGITUDE_DIMENSION"
            elif name=="nj":
                _type = "ALONG_TRACK_DIMENSION"
            elif name=="ni":
                _type = "CROSS_TRACK_DIMENSION"
            elif name=="nv":
                _type = "OTHER"
            else:
                _type = "OTHER"
            return {'Name': dim.name, 'Size': dim.size, 'Type': _type}
        return [_predict_dim_type(d) for d in ncvar.get_dims()]

    def _ValidRanges(ncvar):
        #if hasattr(ncvar, 'valid_range'):
        #    _min, _max = ncvar.valid_range
        #elif hasattr(ncvar, 'valid_min') and hasattr(ncvar, 'valid_max'):
        if hasattr(ncvar, 'valid_min') and hasattr(ncvar, 'valid_max'):
            _min, _max = ncvar.valid_min, ncvar.valid_max
        else:
            return None
        return [{"Min": _min, "Max": _max}]

    def _Scale(ncvar, default: float=1.0):
        if hasattr(ncvar, 'scale_factor'):
            return ncvar.scale_factor
        return default

    def _Offset(ncvar, default: float=0.0):
        if hasattr(ncvar, 'add_offset'):
            return ncvar.add_offset
        return default

    def _FillValues(ncvar):
        if str(ncvar.name).lower()=="time":
            return
        for attribute in ["_FillValue", "missing_value"]:
            if hasattr(ncvar, attribute):
                value = getattr(ncvar, attribute)
                if str(value)=="nan":
                    pass
                elif type(value)==bytes:
                    pass
                else:
                    return [{'Value': value, 'Type': "SCIENCE_FILLVALUE"}]
        return

    def _VariableType(ncvar):
        if not hasattr(ncvar, "coverage_content_type"):
            return
        return {
            'image': "SCIENCE_VARIABLE",
            'thematicClassification': "SCIENCE_VARIABLE",
            'physicalMeasurement': "SCIENCE_VARIABLE",
            'modelResult': "SCIENCE_VARIABLE",
            'auxiliaryInformation': "ANCILLARY_VARIABLE",
            'auxillaryInformation': "ANCILLARY_VARIABLE",  # common typo
            'auxilliaryData': "ANCILLARY_VARIABLE",  # cygnss typo
            'qualityInformation': "QUALITY_VARIABLE",
            'qualityInformaion': "QUALITY_VARIABLE",  # smode typo
            'reference_information': "OTHER",  # smode type
            'referenceInformation': "OTHER",
            'coordinate': "COORDINATE", 
        }[ str(ncvar.coverage_content_type).strip() ]

    def _VariableSubType(ncvar):
        """Unused: (SCIENCE_SCALAR, SCIENCE_VECTOR, SCIENCE_ARRAY)"""
        if any([a.startswith("flag") for a in ncvar.ncattrs()]):
            return "SCIENCE_EVENTFLAG"
        elif Variable._DataType(ncvar)=="char":
            return "OTHER"
        else:
            return

    def _IndexRanges(ncvar):
        grp = ncvar.group()
        if grp.parent:
            grp = grp.parent
        try:
            latmin, latmax = grp.geospatial_lat_min, grp.geospatial_lat_max
            lonmin, lonmax = grp.geospatial_lon_min, grp.geospatial_lon_max
        except AttributeError as e:
            return
        else:
            IndexRanges = {'LatRange': [], 'LonRange': []}
            # Try to drop cardinal direction chars before returning dict
            for r in [latmin, latmax]:
                r = float(_num_sanitize.sub('', r)) if type(r) is str else r
                IndexRanges['LatRange'].append(r)
            for r in [lonmin, lonmax]:
                r = float(_num_sanitize.sub('', r)) if type(r) is str else r
                IndexRanges['LonRange'].append(r)
            return IndexRanges

    def _MeasurementIdentifiers(ncvar):
        return

    def _MetadataSpecification(ncvar):
        """Added to schema in UMM Variable version 1.8"""
        return {"URL": _umm_var,
                "Name": "UMM-Var",
                "Version": _umm_var.split("/v")[-1]}

    def _SamplingIdentifiers(ncvar):
        return

    def _ScienceKeywords(ncvar):
        return

    def _Sets(ncvar):
        """Typically, science variables have quality variables associated 
        with them and can also include other types. This element allows for 
        variables to be grouped together as a set. The set is defined by the 
        name, type, size, and index. The Set class is flexible enough to also 
        include compound variables (a variable that groups related variables 
        together to describe a phenomenon). The data provider will provide 
        the set name, the set type - which is usually the theme of the group 
        or just use the default string of General, the set size - which is the 
        total number of variables in the set, and the index - which is just 
        the numbering scheme for each variable in the set.
        """
        #if hasattr(ncvar, "ancillary_variables"):
        #    related_variables = ancillary.strip().split(" ")
        return [{'Name': ncvar.name, 'Type': "General", 'Size': 1, 'Index': 1}]


class Record:
    def __init__(self, profile):
        self.profile = profile
        self.meta = {}

    def fill(self, data, prop: str):
        if not hasattr(self.profile, f"_{prop}"):
            return
        value = getattr(self.profile, f"_{prop}")(data)
        if value:
            self.meta[prop] = value


def process_variable(ncvar):
    record = Record(profile=Variable)
    for p in Variable.schema['properties']:
        record.fill(data=ncvar, prop=p)
    return record.meta


def process_granule(ncfile: str):
    def _ncgrp(x, records: list=[]):
        groups = x.groups
        for group in list(groups):
            records = _ncgrp(groups[group], records=records)
        variables = x.variables
        for variable in variables:
            records.append(process_variable(variables[variable]))
        return records
    try:
        with Dataset(ncfile, mode="r") as ds:
            records = _ncgrp(ds)
    except OSError as e:
        raise e
    return records


def main(granule:str, collection:str=None, variable:str=None, environment:str=None):
    ummv = process_granule(granule)

    # If input 'variable' was provided, exclude all other variables.
    if variable:
        ummv = [m for m in ummv if m['Name']==variable]

    # If target 'collection' was not provided, return ummvar records to stdout.
    if collection is None:
        return ummv  # No concept-id provided to script as input.
    else: 
        # Otherwise, try to read launchpad token from the local json cert:
        launchpad_token = _read_lptoken(environment=environment)
        if launchpad_token is None:
            return ummv

    if environment in ['sit', 'uat']:
        _cmr  = f"cmr.{f'{environment}.'}earthdata.nasa.gov"
    else:
        _cmr = "cmr.earthdata.nasa.gov"

    with requests.get(
        url=f"https://{_cmr}/search/concepts/{collection}.umm_json", 
        headers={'Authorization': str(launchpad_token)}) as r:
            ShortName = r.json().get("ShortName")
    if ShortName is None:
        raise Exception(f"Failed to obtain collection ShortName for input concept-id '{collection}'. Abort")

    ingest_log = {}
    for m in ummv:
        name = m['Name']
        if name.startswith("/"):
            name = name[1:].replace("/","_")
        nid = f"{ShortName}-{name}"
        ingest_url = f"https://{_cmr}/ingest/collections/{collection}/variables/{nid}"
        ingest_data = json.dumps(m,  default=convert, )
        ingest_log[nid] = requests.put(ingest_url, data=ingest_data, headers={
            'Authorization': str(launchpad_token),
            'Content-type': f"application/vnd.nasa.cmr.umm+json;version={_umm_var.split('/v')[-1]}",
            'Accept': "application/json",
        }).json()

    return ingest_log


def _handle_args():
    import argparse
    parser = argparse.ArgumentParser(prog=sys.argv[0], description="Generate UMM Variable records in json format and ingest them to CMR", epilog="jmcnelis@jpl.nasa.gov")
    parser.add_argument("granule", type=str, help="the source data or metadata (netCDF/HDF/json)")
    parser.add_argument("-c", "--collection",  dest="collection",  default=None, help="target 'collection' in CMR, specified by its unique 'concept-id'")
    parser.add_argument("-v", "--variable",    dest="variable",    default=None, help="target 'variable' in the input 'granule', which must a netCDF or HDF file")
    parser.add_argument("-e", "--environment", dest="environment", default="ops", help="target CMR environment, if not the 'ops' environment; either 'uat' or 'sit'")
    return parser.parse_args()


if __name__ == "__main__":
    args = _handle_args()

    results = main(granule=args.granule, 
                   collection=args.collection,
                   variable=args.variable, 
                   environment=args.environment, )

    print(json.dumps(results, indent=2, default=convert, ))
