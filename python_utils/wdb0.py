import os
import psycopg2
import pandas as pd
import numpy as np
import pickle as pkl
import datetime as dt

"""
Functions for reading data from wdb0.
"""

def get_snow_depth_obs(begin_datetime,
                       end_datetime,
                       no_data_value=-99999.0,
                       bounding_box=None,
                       scratch_dir=None,
                       verbose=None):

    """
    Get hourly snow depth observations from the "web_data" database on
    wdb0.

    XXXNote that observations from the end datetime are NOT included. For
    XXXexample, if begin_datetime is 2019-01-01 00 and end_datetime is
    XXX2019-02-01 00, then 31 * 24 = 744 hours of data are gathered, from
    XXX2019-01-01 00 to 2019-01-31 23.
    Note that observations from the end datetime ARE included. For
    example, if begin_datetime is 2019-01-01 00 and end_datetime is
    2019-01-31 23, then 31 * 24 = 744 hours of data are gathered, from
    2019-01-01 00 to 2019-01-31 23.
    """

    file_name = 'wdb0_obs_snow_depth_' + \
                begin_datetime.strftime('%Y%m%d%H') + \
                '_to_' + \
                end_datetime.strftime('%Y%m%d%H') + \
                '.pkl'

    if scratch_dir is not None:
        file_name = os.path.join(scratch_dir, file_name)

    if os.path.isfile(file_name):

        # Retrieve data from pkl file and return.
        file_obj = open(file_name, 'rb')
        obs_snow_depth = pkl.load(file_obj)
        file_obj.close()
        return(obs_snow_depth)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1
    # print('num_hours = {}'.format(num_hours))

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              'point.allstation.obj_identifier, ' + \
              'TRIM(point.allstation.station_id), ' + \
              'TRIM(point.allstation.name), ' + \
              'point.allstation.coordinates[0] AS lon, ' + \
              'point.allstation.coordinates[1] AS lat, ' + \
              'point.allstation.elevation, ' + \
              'point.allstation.recorded_elevation, ' + \
              'date, ' + \
              'value * 100.0 AS obs_snow_depth_cm ' + \
              'FROM point.allstation, ' + \
              'point.obs_snow_depth ' + \
              'WHERE date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND point.allstation.obj_identifier = ' + \
              'point.obs_snow_depth.obj_identifier ' + \
              'AND value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND point.allstation.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND point.allstation.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND point.allstation.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND point.allstation.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY obj_identifier, date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_depth = cursor.fetchall()

    obs_depth_column_list = ['obj_identifier',
                             'station_id',
                             'name',
                             'lon',
                             'lat',
                             'elevation',
                             'recorded_elevation',
                             'date',
                             'obs_snow_depth_cm']

    df = pd.DataFrame(obs_depth, columns=obs_depth_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1,
                                                num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600

        try:
            obs[station_ind, time_ind] = row['obs_snow_depth_cm']
        except:
            print(num_hours)
            print(station_ind, time_ind)
            print(obs)
            print(obs.shape)
            print(row)
            exit(1)

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_snow_depth = {'num_stations': num_stations,
                      'num_hours': num_hours,
                      'station_obj_id': station_obj_id,
                      'station_id': station_id,
                      'station_name': station_name,
                      'station_lon': station_lon,
                      'station_lat': station_lat,
                      'station_elevation': station_elevation,
                      'station_rec_elevation': station_rec_elevation,
                      'obs_datetime': obs_datetime,
                      'values_cm': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_snow_depth, file_obj)
        file_obj.close()

    return(obs_snow_depth)


def get_swe_obs(begin_datetime,
                end_datetime,
                no_data_value=-99999.0,
                bounding_box=None,
                scratch_dir=None,
                verbose=None):

    """
    Get hourly snow water equivalent observations from the "web_data" database
    on wdb0.
    Note that observations from the end datetime ARE included. For
    example, if begin_datetime is 2019-01-01 00 and end_datetime is
    2019-01-31 23, then 31 * 24 = 744 hours of data are gathered, from
    2019-01-01 00 to 2019-01-31 23.
    """

    file_name = 'wdb0_obs_snow_water_equivalent_' + \
                begin_datetime.strftime('%Y%m%d%H') + \
                '_to_' + \
                end_datetime.strftime('%Y%m%d%H') + \
                '.pkl'

    if scratch_dir is not None:
        file_name = os.path.join(scratch_dir, file_name)

    if os.path.isfile(file_name):

        # Retrieve data from pkl file and return.
        file_obj = open(file_name, 'rb')
        obs_swe = pkl.load(file_obj)
        file_obj.close()
        return(obs_swe)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              'point.allstation.obj_identifier, ' + \
              'TRIM(point.allstation.station_id), ' + \
              'TRIM(point.allstation.name), ' + \
              'point.allstation.coordinates[0] AS lon, ' + \
              'point.allstation.coordinates[1] AS lat, ' + \
              'point.allstation.elevation, ' + \
              'point.allstation.recorded_elevation, ' + \
              'date, ' + \
              'value * 1000.0 AS obs_swe_mm ' + \
              'FROM point.allstation, ' + \
              'point.obs_swe ' + \
              'WHERE date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND point.allstation.obj_identifier = ' + \
              'point.obs_swe.obj_identifier ' + \
              'AND value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND point.allstation.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND point.allstation.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND point.allstation.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND point.allstation.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY obj_identifier, date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_swe = cursor.fetchall()

    obs_swe_column_list = ['obj_identifier',
                           'station_id',
                           'name',
                           'lon',
                           'lat',
                           'elevation',
                           'recorded_elevation',
                           'date',
                           'obs_swe_mm']

    df = pd.DataFrame(obs_swe, columns=obs_swe_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1, num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600
        obs[station_ind, time_ind] = row['obs_swe_mm']

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_swe = {'num_stations': num_stations,
               'num_hours': num_hours,
               'station_obj_id': station_obj_id,
               'station_id': station_id,
               'station_name': station_name,
               'station_lon': station_lon,
               'station_lat': station_lat,
               'station_elevation': station_elevation,
               'station_rec_elevation': station_rec_elevation,
               'obs_datetime': obs_datetime,
               'values_mm': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_swe, file_obj)
        file_obj.close()

    return(obs_swe)








def get_swe_obs_df(begin_datetime,
                   end_datetime,
                   no_data_value=-99999.0,
                   bounding_box=None,
                   scratch_dir=None,
                   verbose=None):

    """
    Get hourly snow water equivalent observations from the "web_data" database
    on wdb0. Return results in a pandas dataframe.
    Note that observations from the end datetime ARE included. For
    example, if begin_datetime is 2019-01-01 00 and end_datetime is
    2019-01-31 23, then 31 * 24 = 744 hours of data are gathered, from
    2019-01-01 00 to 2019-01-31 23.
    """

    file_name = 'wdb0_obs_snow_water_equivalent_df_' + \
                begin_datetime.strftime('%Y%m%d%H') + \
                '_to_' + \
                end_datetime.strftime('%Y%m%d%H') + \
                '.pkl'

    if scratch_dir is not None:
        file_name = os.path.join(scratch_dir, file_name)

    if os.path.isfile(file_name):

        # Retrieve data from pkl file and return.
        file_obj = open(file_name, 'rb')
        obs_swe_df = pkl.load(file_obj)
        file_obj.close()
        return(obs_swe_df)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              'point.allstation.obj_identifier, ' + \
              'TRIM(point.allstation.station_id), ' + \
              'TRIM(point.allstation.name), ' + \
              'point.allstation.coordinates[0] AS lon, ' + \
              'point.allstation.coordinates[1] AS lat, ' + \
              'point.allstation.elevation, ' + \
              'point.allstation.recorded_elevation, ' + \
              'date, ' + \
              'value * 1000.0 AS obs_swe_mm ' + \
              'FROM point.allstation, ' + \
              'point.obs_swe ' + \
              'WHERE date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND point.allstation.obj_identifier = ' + \
              'point.obs_swe.obj_identifier ' + \
              'AND value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND point.allstation.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND point.allstation.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND point.allstation.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND point.allstation.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY obj_identifier, date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_swe = cursor.fetchall()

    obs_swe_column_list = ['obj_identifier',
                           'station_id',
                           'name',
                           'lon',
                           'lat',
                           'elevation',
                           'recorded_elevation',
                           'date',
                           'obs_swe_mm']

    obs_swe_df = pd.DataFrame(obs_swe, columns=obs_swe_column_list)
    conn.close()

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_swe_df, file_obj)
        file_obj.close()

    return(obs_swe_df)


def get_prev_snow_depth_obs(target_datetime,
                            num_hours_prev_sd,
                            no_data_value=-99999.0,
                            bounding_box=None,
                            scratch_dir=None,
                            verbose=None):

    """
    Get hourly snow depth observations from the "web_data" database on wdb0
    for num_hours_prev_sd for those stations that report snow depth at
    target_datetime.
    The idea here is to limit the preceding observations we collect to those
    from stations that report snow depth at target_datetime, and to ignore all
    others.
    """

    begin_datetime = target_datetime - dt.timedelta(hours=num_hours_prev_sd)
    end_datetime = target_datetime - dt.timedelta(hours=1)

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_snow_depth_' + \
                    '{}_hours_prior_to_'.format(num_hours_prev_sd) + \
                    target_datetime.strftime('%Y%m%d%H') + \
                    '_snow_depth' + \
                    '.pkl'

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_snow_depth = pkl.load(file_obj)
                file_obj.close()
                return(obs_snow_depth)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              't1.obj_identifier, ' + \
              'TRIM(t3.station_id), ' + \
              'TRIM(t3.name), ' + \
              't3.coordinates[0] AS lon, ' + \
              't3.coordinates[1] AS lat, ' + \
              't3.elevation, ' + \
              't3.recorded_elevation, ' + \
              't2.date, ' + \
              't2.value * 100.0 AS obs_snow_depth_cm ' + \
              'FROM ' + \
              '(' + \
              'SELECT obj_identifier ' + \
              'FROM point.obs_snow_depth ' + \
              'WHERE date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND value IS NOT NULL ' + \
              'GROUP BY obj_identifier' + \
              ') ' + \
              'AS t1, ' + \
              'point.obs_snow_depth AS t2, ' + \
              'point.allstation AS t3 ' + \
              'WHERE t2.date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t1.obj_identifier = t2.obj_identifier ' + \
              'AND t2.obj_identifier = t3.obj_identifier ' + \
              'AND t3.obj_identifier = t1.obj_identifier ' + \
              'AND t2.value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND t3.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND t3.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND t3.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND t3.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY t1.obj_identifier, t2.date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_depth = cursor.fetchall()

    obs_depth_column_list = ['obj_identifier',
                             'station_id',
                             'name',
                             'lon',
                             'lat',
                             'elevation',
                             'recorded_elevation',
                             'date',
                             'obs_snow_depth_cm']

    df = pd.DataFrame(obs_depth, columns=obs_depth_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1,
                                                num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600

        try:
            obs[station_ind, time_ind] = row['obs_snow_depth_cm']
        except:
            print(num_hours)
            print(station_ind, time_ind)
            print(obs)
            print(obs.shape)
            print(row)
            exit(1)

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_snow_depth = {'num_stations': num_stations,
                      'num_hours': num_hours,
                      'station_obj_id': station_obj_id,
                      'station_id': station_id,
                      'station_name': station_name,
                      'station_lon': station_lon,
                      'station_lat': station_lat,
                      'station_elevation': station_elevation,
                      'station_rec_elevation': station_rec_elevation,
                      'obs_datetime': obs_datetime,
                      'values_cm': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_snow_depth, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_snow_depth)


def get_air_temp_obs(begin_datetime,
                     end_datetime,
                     no_data_value=-99999.0,
                     bounding_box=None,
                     scratch_dir=None,
                     verbose=None):

    """
    Get hourly air temperature observations from the "web_data" database on
    wdb0.
    """

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_air_temp_' + \
                    begin_datetime.strftime('%Y%m%d%H') + \
                    '_to_' + \
                    end_datetime.strftime('%Y%m%d%H') + \
                    '.pkl'

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_air_temp = pkl.load(file_obj)
                file_obj.close()
                return(obs_air_temp)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1
    # print('num_hours = {}'.format(num_hours))

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              'point.allstation.obj_identifier, ' + \
              'TRIM(point.allstation.station_id), ' + \
              'TRIM(point.allstation.name), ' + \
              'point.allstation.coordinates[0] as lon, ' + \
              'point.allstation.coordinates[1] as lat, ' + \
              'point.allstation.elevation, ' + \
              'point.allstation.recorded_elevation, ' + \
              'date, ' + \
              'value AS obs_air_temp_deg_c ' + \
              'FROM point.allstation, point.obs_airtemp ' + \
              'WHERE date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND point.allstation.obj_identifier = ' + \
              'point.obs_airtemp.obj_identifier ' + \
              'AND value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND point.allstation.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND point.allstation.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND point.allstation.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND point.allstation.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY obj_identifier, date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    fetched_airtemp = cursor.fetchall()

    obs_air_temp_column_list = ['obj_identifier',
                                'station_id',
                                'name',
                                'lon',
                                'lat',
                                'elevation',
                                'recorded_elevation',
                                'date',
                                'obs_air_temp_deg_c']

    df = pd.DataFrame(fetched_airtemp, columns=obs_air_temp_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1,
                                                num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600

        obs[station_ind, time_ind] = row['obs_air_temp_deg_c']

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_air_temp = {'num_stations': num_stations,
                    'num_hours': num_hours,
                    'station_obj_id': station_obj_id,
                    'station_id': station_id,
                    'station_name': station_name,
                    'station_lon': station_lon,
                    'station_lat': station_lat,
                    'station_elevation': station_elevation,
                    'station_rec_elevation': station_rec_elevation,
                    'obs_datetime': obs_datetime,
                    'values_deg_c': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_air_temp, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_air_temp)


def get_prev_air_temp_obs(target_datetime,
                          num_hours_prev_sd,
                          no_data_value=-99999.0,
                          bounding_box=None,
                          scratch_dir=None,
                          verbose=None):

    """
    Get hourly air temperature observations from the "web_data" database on
    wdb0 for num_hours_prev_sd for those stations that report snow depth at
    target_datetime.
    The idea here is to limit the preceding observations we collect to those
    from stations that report snow depth at target_datetime, and to ignore all
    others.
    """

    begin_datetime = target_datetime - dt.timedelta(hours=num_hours_prev_sd)
    end_datetime = target_datetime - dt.timedelta(hours=1)

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_air_temp_' + \
                    '{}_hours_prior_to_'.format(num_hours_prev_sd) + \
                    target_datetime.strftime('%Y%m%d%H') + \
                    '_snow_depth' + \
                    '.pkl'

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_air_temp = pkl.load(file_obj)
                file_obj.close()
                return(obs_air_temp)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              't1.obj_identifier, ' + \
              'TRIM(t3.station_id), ' + \
              'TRIM(t3.name), ' + \
              't3.coordinates[0] AS lon, ' + \
              't3.coordinates[1] AS lat, ' + \
              't3.elevation, ' + \
              't3.recorded_elevation, ' + \
              't2.date, ' + \
              't2.value AS obs_air_temp_deg_c ' + \
              'FROM ' + \
              '(' + \
              'SELECT obj_identifier ' + \
              'FROM point.obs_snow_depth ' + \
              'WHERE date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND value IS NOT NULL ' + \
              'GROUP BY obj_identifier' + \
              ') ' + \
              'AS t1, ' + \
              'point.obs_airtemp AS t2, ' + \
              'point.allstation AS t3 ' + \
              'WHERE t2.date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t1.obj_identifier = t2.obj_identifier ' + \
              'AND t2.obj_identifier = t3.obj_identifier ' + \
              'AND t3.obj_identifier = t1.obj_identifier ' + \
              'AND t2.value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND t3.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND t3.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND t3.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND t3.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY t1.obj_identifier, t2.date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    fetched_airtemp = cursor.fetchall()

    obs_air_temp_column_list = ['obj_identifier',
                                'station_id',
                                'name',
                                'lon',
                                'lat',
                                'elevation',
                                'recorded_elevation',
                                'date',
                                'obs_air_temp_deg_c']

    df = pd.DataFrame(fetched_airtemp, columns=obs_air_temp_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1,
                                                num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600

        try:
            obs[station_ind, time_ind] = row['obs_air_temp_deg_c']
        except:
            print(num_hours)
            print(station_ind, time_ind)
            print(obs)
            print(obs.shape)
            print(row)
            exit(1)

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_air_temp = {'num_stations': num_stations,
                    'num_hours': num_hours,
                    'station_obj_id': station_obj_id,
                    'station_id': station_id,
                    'station_name': station_name,
                    'station_lon': station_lon,
                    'station_lat': station_lat,
                    'station_elevation': station_elevation,
                    'station_rec_elevation': station_rec_elevation,
                    'obs_datetime': obs_datetime,
                    'values_deg_c': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_air_temp, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_air_temp)


def get_snwd_snowfall_obs(target_datetime,
                          duration_hours,
                          no_data_value=-99999.0,
                          bounding_box=None,
                          scratch_dir=None,
                          verbose=None):

    """
    Get snowfall observations from the "web_data" database on wdb0 having
    duration of duration_hours, an observation time of target_datetime, and
    limit the query to those associated with observed snow depth at
    target_datetime.
    The idea here is to limit the snowfall observations we collect to those
    from stations that report snow depth at target_datetime, and to ignore all
    others.
    """

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_snowfall_' + \
                    '{}_hours_ending_'.format(duration_hours) + \
                    target_datetime.strftime('%Y%m%d%H') + \
                    '_snow_depth' + \
                    '.pkl'

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_snowfall = pkl.load(file_obj)
                file_obj.close()
                return(obs_snowfall)

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              't1.obj_identifier, ' + \
              'TRIM(t3.station_id), ' + \
              'TRIM(t3.name), ' + \
              't3.coordinates[0] AS lon, ' + \
              't3.coordinates[1] AS lat, ' + \
              't3.elevation, ' + \
              't3.recorded_elevation, ' + \
              't2.date, ' + \
              't2.value * 100.0 AS obs_snowfall_cm ' + \
              'FROM ' + \
              '(' + \
              'SELECT obj_identifier ' + \
              'FROM point.obs_snow_depth ' + \
              'WHERE date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND value IS NOT NULL ' + \
              'GROUP BY obj_identifier' + \
              ') ' + \
              'AS t1, ' + \
              'point.obs_snowfall_raw AS t2, ' + \
              'point.allstation AS t3 ' + \
              'WHERE t2.date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.duration = {} '.format(duration_hours * 3600) + \
              'AND t1.obj_identifier = t2.obj_identifier ' + \
              'AND t2.obj_identifier = t3.obj_identifier ' + \
              'AND t3.obj_identifier = t1.obj_identifier ' + \
              'AND t2.value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND t3.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND t3.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND t3.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND t3.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY t1.obj_identifier, t2.date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_snowfall = cursor.fetchall()

    obs_snowfall_column_list = ['obj_identifier',
                                'station_id',
                                'name',
                                'lon',
                                'lat',
                                'elevation',
                                'recorded_elevation',
                                'date',
                                'obs_snowfall_cm']

    df = pd.DataFrame(obs_snowfall, columns=obs_snowfall_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    # GF - 2nd dim used to be num_hours
    obs = np.ma.empty([1], dtype=float)
    obs[0] = no_data_value
    obs[0] = np.ma.masked
    # print(len(df))
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                # GF - 2nd dim used to be num_hours
                obs = np.ma.append(obs,
                                   np.ma.empty([1],
                                               dtype=float),
                                   axis=0)
                obs[station_ind] = no_data_value
                obs[station_ind] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # print(type(row['obj_identifier']))
        # if row['obj_identifier'] == 11929:
        #     print(row)
        #     print(row['obs_snowfall_cm'])

        try:
            obs[station_ind] = row['obs_snowfall_cm']
        except:
            print(obs)
            print(obs.shape)
            print(row)
            exit(1)

    num_stations = station_ind + 1
    print(len(obs))

    # Place results in a dictionary.
    obs_snowfall = {'num_stations': num_stations,
                    'station_obj_id': station_obj_id,
                    'station_id': station_id,
                    'station_name': station_name,
                    'station_lon': station_lon,
                    'station_lat': station_lat,
                    'station_elevation': station_elevation,
                    'station_rec_elevation': station_rec_elevation,
                    'obs_datetime': target_datetime,
                    'values_cm': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - target_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_snowfall, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_snowfall)


def get_snwd_prcp_obs(target_datetime,
                      duration_hours,
                      no_data_value=-99999.0,
                      bounding_box=None,
                      scratch_dir=None,
                      verbose=None):

    """
    Get precipitation observations from the "web_data" database on wdb0 having
    duration of duration_hours, an observation time of target_datetime, and
    limit the query to those associated with observed snow depth at
    target_datetime.
    The idea here is to limit the precipitation observations we collect to
    those from stations that report snow depth at target_datetime, and to
    ignore all others.
    """

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_precipitation_' + \
                    '{}_hours_ending_'.format(duration_hours) + \
                    target_datetime.strftime('%Y%m%d%H') + \
                    '_snow_depth' + \
                    '.pkl'

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_precip = pkl.load(file_obj)
                file_obj.close()
                return(obs_precip)

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              't1.obj_identifier, ' + \
              'TRIM(t3.station_id), ' + \
              'TRIM(t3.name), ' + \
              't3.coordinates[0] AS lon, ' + \
              't3.coordinates[1] AS lat, ' + \
              't3.elevation, ' + \
              't3.recorded_elevation, ' + \
              't2.date, ' + \
              't2.value * 1000.0 AS obs_precip_mm ' + \
              'FROM ' + \
              '(' + \
              'SELECT obj_identifier ' + \
              'FROM point.obs_snow_depth ' + \
              'WHERE date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND value IS NOT NULL ' + \
              'GROUP BY obj_identifier' + \
              ') ' + \
              'AS t1, ' + \
              'point.obs_precip_raw AS t2, ' + \
              'point.allstation AS t3 ' + \
              'WHERE t2.date = \'' + \
              target_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.duration = {} '.format(duration_hours * 3600) + \
              'AND t1.obj_identifier = t2.obj_identifier ' + \
              'AND t2.obj_identifier = t3.obj_identifier ' + \
              'AND t3.obj_identifier = t1.obj_identifier ' + \
              'AND t2.value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND t3.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND t3.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND t3.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND t3.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY t1.obj_identifier, t2.date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    obs_precip = cursor.fetchall()

    obs_precip_column_list = ['obj_identifier',
                              'station_id',
                              'name',
                              'lon',
                              'lat',
                              'elevation',
                              'recorded_elevation',
                              'date',
                              'obs_precip_mm']

    df = pd.DataFrame(obs_precip, columns=obs_precip_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    # GF - 2nd dim used to be num_hours
    obs = np.ma.empty([1], dtype=float)
    obs[0] = no_data_value
    obs[0] = np.ma.masked
    # print(len(df))
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                # GF - 2nd dim used to be num_hours
                obs = np.ma.append(obs,
                                   np.ma.empty([1],
                                               dtype=float),
                                   axis=0)
                obs[station_ind] = no_data_value
                obs[station_ind] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        try:
            obs[station_ind] = row['obs_precip_mm']
        except:
            print(obs)
            print(obs.shape)
            print(row)
            exit(1)

    num_stations = station_ind + 1
    print(len(obs))

    # Place results in a dictionary.
    obs_precip = {'num_stations': num_stations,
                  'station_obj_id': station_obj_id,
                  'station_id': station_id,
                  'station_name': station_name,
                  'station_lon': station_lon,
                  'station_lat': station_lat,
                  'station_elevation': station_elevation,
                  'station_rec_elevation': station_rec_elevation,
                  'obs_datetime': target_datetime,
                  'values_mm': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - target_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_precip, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_precip)



























def  get_prv_air_temp_obs(target_datetime,
                          num_hours_prev,
                          no_data_value=-99999.0,
                          bounding_box=None,
                          scratch_dir=None,
                          verbose=None):

    """
    Get hourly air temperature observations from the "web_data" database on
    wdb0 for num_hours_prev prior to (but not including) target_datetime.
    """

    begin_datetime = target_datetime - dt.timedelta(hours=num_hours_prev)
    end_datetime = target_datetime - dt.timedelta(hours=1)

    # Only use .pkl files if there is no bounding box.
    if bounding_box is None:

        file_name = 'wdb0_obs_air_temp_' + \
                    '{}_to_'.format(begin_datetime.strftime('%Y%m%d%H')) + \
                    '{}.pkl'.format(end_datetime.strftime('%Y%m%d%H'))

        if scratch_dir is not None:
            file_name = os.path.join(scratch_dir, file_name)

            if os.path.isfile(file_name):

                # Retrieve data from pkl file and return.
                file_obj = open(file_name, 'rb')
                obs_air_temp = pkl.load(file_obj)
                file_obj.close()
                return(obs_air_temp)

    time_range = end_datetime - begin_datetime
    num_hours = time_range.days * 24 + time_range.seconds // 3600 + 1

    # Open the web database.
    conn_string = "host='wdb0.dmz.nohrsc.noaa.gov' dbname='web_data'"
    conn = psycopg2.connect(conn_string)
    conn.set_client_encoding("utf-8")
    cursor = conn.cursor()

    # Define a SQL statement.
    sql_cmd = 'SELECT ' + \
              't3.obj_identifier, ' + \
              'TRIM(t3.station_id), ' + \
              'TRIM(t3.name), ' + \
              't3.coordinates[0] AS lon, ' + \
              't3.coordinates[1] AS lat, ' + \
              't3.elevation, ' + \
              't3.recorded_elevation, ' + \
              't2.date, ' + \
              't2.value AS obs_air_temp_deg_c ' + \
              'FROM ' + \
              'point.obs_airtemp AS t2, ' + \
              'point.allstation AS t3 ' + \
              'WHERE t2.date >= \'' + \
              begin_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.date <= \'' + \
              end_datetime.strftime('%Y-%m-%d %H:%M:%S') + \
              '\' ' + \
              'AND t2.obj_identifier = t3.obj_identifier ' + \
              'AND t2.value IS NOT NULL '

    if bounding_box is not None:
        sql_cmd = sql_cmd + \
                  'AND t3.coordinates[0] >= ' + \
                  '{} '.format(bounding_box[0]) + \
                  'AND t3.coordinates[0] < ' + \
                  '{} '.format(bounding_box[1]) + \
                  'AND t3.coordinates[1] >= ' + \
                  '{} '.format(bounding_box[2]) + \
                  'AND t3.coordinates[1] < ' + \
                  '{} '.format(bounding_box[3])

    sql_cmd = sql_cmd + 'ORDER BY t3.obj_identifier, t2.date;'

    if verbose:
        print('INFO: psql command "{}"'.format(sql_cmd))

    cursor.execute(sql_cmd)

    # The result below is just a huge list of tuples.
    fetched_airtemp = cursor.fetchall()

    obs_air_temp_column_list = ['obj_identifier',
                                'station_id',
                                'name',
                                'lon',
                                'lat',
                                'elevation',
                                'recorded_elevation',
                                'date',
                                'obs_air_temp_deg_c']

    df = pd.DataFrame(fetched_airtemp, columns=obs_air_temp_column_list)

    # This section organizes the query results into lists and arrays.

    station_ind = -1
    current_station_obj_id = -1
    station_obj_id = []
    station_id = []
    station_name = []
    station_lon = []
    station_lat = []
    station_elevation = []
    station_rec_elevation = []
    # Create a 2-d [time, station] array.
    obs = np.ma.empty([1, num_hours], dtype=float)
    obs[0,:] = no_data_value
    obs[0,:] = np.ma.masked
    for ind, row in df.iterrows():
        if row['obj_identifier'] != current_station_obj_id:
            station_ind += 1
            if station_ind > 0:
                # Just finished all data for previous station.
                obs = np.ma.append(obs,
                                   np.ma.empty([1,
                                                num_hours],
                                               dtype=float),
                                   axis=0)
                obs[station_ind,:] = no_data_value
                obs[station_ind,:] = np.ma.masked
            # New station
            station_obj_id.append(row['obj_identifier'])
            station_id.append(row['station_id'])
            station_name.append(row['name'])
            station_lon.append(row['lon'])
            station_lat.append(row['lat'])
            station_elevation.append(row['elevation'])
            station_rec_elevation.append(row['recorded_elevation'])

            current_station_obj_id = station_obj_id[station_ind]

        # Add the observation to the obs array.
        time_diff = row['date'] - begin_datetime
        time_ind = time_diff.days * 24 + time_diff.seconds // 3600

        obs[station_ind, time_ind] = row['obs_air_temp_deg_c']

    num_stations = station_ind + 1

    obs_datetime = [begin_datetime +
                    dt.timedelta(hours=i) for i in range(num_hours)]

    # Place results in a dictionary.
    obs_air_temp = {'num_stations': num_stations,
                    'num_hours': num_hours,
                    'station_obj_id': station_obj_id,
                    'station_id': station_id,
                    'station_name': station_name,
                    'station_lon': station_lon,
                    'station_lat': station_lat,
                    'station_elevation': station_elevation,
                    'station_rec_elevation': station_rec_elevation,
                    'obs_datetime': obs_datetime,
                    'values_deg_c': obs}

    # Create the pkl file if all data fetched is more than 60 days earlier
    # than the current date/time.
    lag = dt.datetime.utcnow() - end_datetime
    if bounding_box is None and \
       lag > dt.timedelta(days=60):
        file_obj = open(file_name, 'wb')
        pkl.dump(obs_air_temp, file_obj)
        file_obj.close()
        if verbose:
            print('INFO: wrote query results to {}.'.format(file_name))

    return(obs_air_temp)
