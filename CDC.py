#!/usr/bin/env python
# coding: utf-8

# In[1]:


#import library
from kafka import KafkaConsumer
import json
import pandas as pd
from sqlalchemy import create_engine, text
import time
import os
from datetime import datetime
from urllib.parse import quote_plus
from sqlalchemy.types import NVARCHAR
from multiprocessing import Pool
from multiprocessing import Process


# In[2]:


def take_config_from_file(file_dir):
    with open(file_dir) as f:
        lines = f.readlines()
        f.close()
    return lines[1]


# In[3]:


def take_table_name_from_file(file_dir):
    list_table_name = []
    with open(file_dir) as f:
        lines = f.readlines()
        f.close()
    list_table_tmp = lines[0].split(",")
    for item in list_table_tmp:
        if(item[0] == ' '):
            item = item[1:]
        list_table_name.append(item)
    f.close()
    return list_table_name


# In[4]:


def take_dt_col_name_from_file(file_dir):
    date_col = []
    with open(file_dir) as f:
        lines = f.readlines()
        f.close()
    list_col_tmp = lines[0].split(",")
    for item in list_col_tmp:
        if(item[0] == ' '):
            item = item[1:]
        date_col.append(item)
    f.close()
    return date_col


# In[5]:


def take_table_name(df):
    source = pd.DataFrame([df.loc[0,'source']])
    table_name = source.loc[0,'table']
    return table_name


# In[6]:


#take topic name
def take_list_topic_name(list_table_name, prefix, database_source):
    list_topic = []
    for table_name in list_table_name:
        topic_name = f'{prefix}.{database_source}.{table_name}'
        list_topic.append(topic_name)
    return list_topic


# In[7]:


#read json data to dataframe
def read_json_to_df(json):
    data = pd.DataFrame([json])
    return data


# In[8]:


def take_time():
    now = datetime.now()
    # dd/mm/YY H:M:S
    dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
    return dt_string


# In[9]:


def insert_data(df,table_name):
    #Take new data
    cdc_table = pd.DataFrame([df.loc[0,'after']]) 
    txt_cols = cdc_table.select_dtypes(include = ['object']).columns.values.tolist()
    #Change nano epoch time to datetime
    for col in cdc_table.columns:
        if(col in date_col):
            try:
                epoch_time = cdc_table.loc[0, col]
                dt_obj = datetime.utcfromtimestamp(epoch_time/1000)
                cdc_table.loc[0, col] = dt_obj
            except Exception as e:
                cdc_table.loc[0,col] = None
                cdc_table[col] = pd.to_datetime(cdc_table[col],errors='coerce')
    cdc_table.to_sql(f'{table_name}', engine, if_exists='append', index = False, dtype = {col_name: NVARCHAR for col_name in txt_cols}) 
    f = open(f".\CDC_logs\cdc_log_{database_source}.txt", "a")
    f.write(f"{table_name}\tID\t{cdc_table.loc[0,'ID']}\t{take_time()}\tInsert\n")
    f.close()


# In[10]:


def update_data(df,table_name):
    cdc_table = pd.DataFrame([df.loc[0,'after']])
    txt_cols = cdc_table.select_dtypes(include = ['object']).columns.values.tolist()
    #string set by loop
    set_str = "SET"
    for col in cdc_table.columns:
        set_str = set_str + f" {col} = t.{col},\n" #SQL command
        if(col in date_col):
            try:
                epoch_time = cdc_table.loc[0, col]
                dt_obj = datetime.utcfromtimestamp(epoch_time/1000)
                cdc_table.loc[0, col] = dt_obj
            except Exception as e:
                cdc_table.loc[0,col] = None
                cdc_table[col] = pd.to_datetime(cdc_table[col],errors='coerce')
            
    sql = f"UPDATE dbo.{table_name}\n" + set_str[:-2] + "\nFROM temp t " +f"WHERE dbo.{table_name}.ID = t.ID"
    
    #delete temp table after complete
    sql_del_temp = "Drop table temp"
        
    #create temp table to reduce time to reconize columns type
    cdc_table.to_sql('temp', engine, if_exists='replace', dtype = {col_name: NVARCHAR for col_name in txt_cols}, index = False)

    #run sql command
    with engine.begin() as conn:
        conn.execute(text(sql))
        conn.execute(text(sql_del_temp))
        f = open(f".\CDC_logs\cdc_log_{database_source}.txt", "a")
        f.write(f"{table_name}\tID\t{cdc_table.loc[0,'ID']}\t{take_time()}\tUpdate\n")
        f.close()


# In[11]:


def delete_data(df,table_name):
    cdc_table = pd.DataFrame([df.loc[0,'before']])
    
    sql = f"DELETE FROM dbo.{table_name} WHERE dbo.{table_name}.ID = {cdc_table.loc[0,'ID']}"

    with engine.begin() as conn:
        conn.execute(text(sql))
        f = open(f".\CDC_logs\cdc_log_{database_source}.txt", "a", encoding="utf-8")
        f.write(f"{table_name}\tID\t{cdc_table.loc[0,'ID']}\t{take_time()}\tDelete\n")
        f.close()


# In[12]:


#Use file table to take all table
def all_table_name(file_dir_table):
    try:
        list_table_name = take_table_name_from_file(file_dir_table)
    except IndexError:
        list_table_name = []
    return list_table_name


# In[13]:


#define the topic list
def Consumer(table_name, bootstrap_servers, group_id, prefix, database_source):
    list_topic = take_list_topic_name([table_name], prefix, database_source)

    # Initialize consumer variable
    consumer = KafkaConsumer (list_topic[0], 
                              bootstrap_servers = bootstrap_servers,
                              auto_offset_reset='earliest', 
                              enable_auto_commit=True,
                              auto_commit_interval_ms=5000,
                              group_id=f'{group_id}_table_{table_name}',
                              max_partition_fetch_bytes=10485760)
    
    for msg in consumer:
        try:
        #Read data from comsumer
            data = json.loads(msg.value)
            df = read_json_to_df(data)
            #Take change data
            df = pd.DataFrame([df.loc[0,'payload']])
            #take table name
            table_name = take_table_name(df)
            #Check action
            if(df.loc[0,'before'] == None and df.loc[0,'after'] == None):
                continue
            elif (df.loc[0,'before'] == None):
                insert_data(df,table_name)
            elif (df.loc[0,'after'] == None):
                delete_data(df,table_name)
            else:
                update_data(df,table_name)
        #Temporary use try except to avoid bug when read null message
        except TypeError:
            time.sleep(0.001) 


# In[14]:


if __name__ == "__main__":
    #file directory
    file_dir_ip_and_group = 'Config/config_ip_and_group_id.txt'
    file_dir_dt_col = 'Table/dt_col.txt'
    file_dir_config_source = 'Config/config_source.txt'
    file_dir_config_destination = 'Config/config_destination.txt'
    
    #take config source
    username_source, password_source, hostname_source, port_source, database_source, prefix \
    = take_config_from_file(file_dir_config_source).split('\t')
    
    #take config destination
    username_destination, password_destination, hostname_destination, port_destination, database_destination \
    = take_config_from_file(file_dir_config_destination).split('\t')
    
    #take config host and group id
    ip_host, group_id = take_config_from_file(file_dir_ip_and_group).split('\t')
    
    #take columns datetime
    date_col = take_dt_col_name_from_file(file_dir_dt_col)
    
    #create log
    for action in ['Insert','Update','Delete']:
        file_dir_log = f'CDC_logs/cdc_log_{database_source}_{action}.txt'
        if (os.path.isfile(file_dir_log)) == False:
            f = open(f"{file_dir_log}", "a", encoding="utf-8")
            f.write("Table\tID\tcreate_at\ttype\n")
            f.close()

    # Define server with port
    bootstrap_servers = [f'{ip_host}:9092',f'{ip_host}:9093',f'{ip_host}:9094']

    #define the connect engine
    password_destination = quote_plus(password_destination)
    engine = create_engine(f'mssql+pymssql://{username_destination}:{password_destination}@{hostname_destination}:{port_destination}/{database_destination}') 
    
    list_process = []
    #Create process
    file_dir_table = f'Table/cdc_table.txt'
    list_table_name = all_table_name(file_dir_table)
    for table_name in list_table_name:
        process = Process(target=Consumer, args=(table_name, bootstrap_servers, group_id, prefix, database_source))
        list_process.append(process)
    #start project
    for process in list_process:
        process.start()
    #block main
    for process in list_process:
        process.join()

