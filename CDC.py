#!/usr/bin/env python
# coding: utf-8

# In[1]:


#import library
from kafka import KafkaConsumer
from kafka import TopicPartition
from kafka.structs import OffsetAndMetadata
import json
import pandas as pd
from sqlalchemy import create_engine, text
import time
import os
from datetime import datetime
from sqlalchemy.types import NVARCHAR, DECIMAL
from multiprocessing import Pool
from multiprocessing import Process
import logging
import time
from sqlalchemy.engine import URL
#import gc
from sqlalchemy import text


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
    with open(file_dir, encoding="utf8") as f:
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

def round_robin_sublists(l, n=4):
    lists = [[] for _ in range(n)]
    i = 0
    for elem in l:
        lists[i].append(elem)
        i = (i + 1) % n
    return lists

# In[9]:


def insert_data(json,table_name,date_col, database_source, engine):
    #Take new data
    cdc_table = pd.DataFrame(json) 
    #txt_cols = cdc_table.select_dtypes(include = ['object']).columns.values.tolist()
    #temp_dec = set(decimal_col)
    #nvarchar_col = [x for x in txt_cols if x not in temp_dec]
    #Change nano epoch time to datetime
    for col in cdc_table.columns:
        if(col in date_col):
            for i in cdc_table.index:
                try:
                    epoch_time = cdc_table.loc[i, col]
                    dt_obj = datetime.utcfromtimestamp(epoch_time/1000)
                    cdc_table.loc[i, col] = dt_obj
                except Exception as e:
                    cdc_table.loc[i,col] = ''
            cdc_table[col] = pd.to_datetime(cdc_table[col],errors='coerce')

    #nvarchar = {col_name: NVARCHAR for col_name in nvarchar_col}
    #decimal = {decimal_name: DECIMAL for decimal_name in decimal_col}
    #change_dtype = {**nvarchar}

    for i in range(600):  # If load fails due to a deadlock, try 600 more times
        try:
            cdc_table.to_sql(f'{table_name}', 
                             engine, 
                             if_exists='append', 
                             index = False) 
                             #dtype = change_dtype)
            f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Insert.txt", "a")
            for i in cdc_table.index:
                f.write(f"{table_name}\tID\t{cdc_table.loc[i,'ID']}\t{take_time()}\tInsert\n")
            f.close()
            break
        except Exception as ex:
            if (i == 599):
                f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Error.txt", "a")
                for i in cdc_table.index:
                    f.write(f"{table_name}\tID\t{cdc_table.loc[i,'ID']}\t{take_time()}\tInsert\n")
                f.close()
                return
            time.sleep(0.1)

# In[10]:


def update_data(json,table_name,date_col, database_source, engine):
    cdc_table = pd.DataFrame(json) 
    #txt_cols = cdc_table.select_dtypes(include = ['object']).columns.values.tolist()
    #temp_dec = set(decimal_col)
    #nvarchar_col = [x for x in txt_cols if x not in temp_dec]
    #string set by loop
    set_str = "SET"
    for col in cdc_table.columns:
        set_str = set_str + f" [{col}] = td.[{col}],\n" #SQL command
        if(col in date_col):
            for i in cdc_table.index:
                try:
                    epoch_time = cdc_table.loc[i, col]
                    dt_obj = datetime.utcfromtimestamp(epoch_time/1000)
                    cdc_table.loc[i, col] = dt_obj
                except Exception as e:
                    cdc_table.loc[i,col] = ''
            cdc_table[col] = pd.to_datetime(cdc_table[col],errors='coerce')
            
    sql = f"UPDATE dbo.{table_name}\n" + set_str[:-2] + f"\nFROM temp_{table_name}_update td " +f"WHERE dbo.{table_name}.ID = td.ID"
    
    #delete temp table after complete
    sql_del_temp = f"Drop table temp_{table_name}_update"
    
    #create temp table to update

    #nvarchar = {col_name: NVARCHAR for col_name in nvarchar_col}
    #decimal = {decimal_name: DECIMAL for decimal_name in decimal_col}
    #change_dtype = {**nvarchar}
    
    sql_create_temp = f"SELECT TOP 0 * INTO [temp_{table_name}_update] FROM [{table_name}]"
    engine.execute(text(sql_create_temp))

    cdc_table.to_sql(f'temp_{table_name}_update', 
                        engine, 
                        if_exists='append', 
                        index = False) 
                        #dtype = change_dtype)

              
    #run sql command

    engine.execute(text(sql)) #execute the update
      
    engine.execute(text(sql_del_temp)) #execute the delete
    f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Update.txt", "a")
    for i in cdc_table.index:
        f.write(f"{table_name}\tID\t{cdc_table.loc[i,'ID']}\t{take_time()}\tUpdate\n")
    f.close()



# In[11]:


def delete_data(json,table_name,date_col, database_source, engine):
    cdc_table = pd.DataFrame(json)
    index = cdc_table['ID']
    index_tuple = tuple(index)
    sql = f"DELETE FROM dbo.{table_name} WHERE dbo.{table_name}.ID in {index_tuple}"


    engine.execute(text(sql))
    f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Delete.txt", "a", encoding="utf-8")
    for i in cdc_table.index:
        f.write(f"{table_name}\tID\t{cdc_table.loc[i,'ID']}\t{take_time()}\tDelete\n")
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
def Consumer(table_name, bootstrap_servers, group_id, prefix, database_source, date_col, username_destination, password_destination, hostname_destination, port_destination, database_destination):
    #define the connect engine
    connection_url = URL.create(
        "mssql+pyodbc",
        username=username_destination,
        password=password_destination,
        host=hostname_destination,
        port=port_destination,
        database=database_destination,
        query={
            "driver": "ODBC Driver 17 for SQL Server"
        },
    )
    engine = create_engine(connection_url, fast_executemany=True).connect()
    
    list_topic = take_list_topic_name([table_name], prefix, database_source)
    
    print(f'start consumer for {table_name}')
    # Initialize consumer variable
    consumer = KafkaConsumer (list_topic[0], 
                              bootstrap_servers = bootstrap_servers,
                              auto_offset_reset='earliest', 
                              enable_auto_commit=False,
                              group_id=f'{group_id}_table_{table_name[4:]}',
                              max_partition_fetch_bytes=10485760)
    
    list_msg_insert = []
    list_msg_delete = []
    list_msg_update = []
    is_pk = False

    for msg in consumer:
        try:
        #take current and end offset
            partitions = [TopicPartition(list_topic[0], p) for p in consumer.partitions_for_topic(list_topic[0])]
            last_offset_per_partition = consumer.end_offsets(partitions)
            end_offset = list(last_offset_per_partition.values())[0]
            current_offset = consumer.position(TopicPartition(topic=list_topic[0], partition=0))
            
            #Read data from comsumer
            data = json.loads(msg.value)
            
            #take change data
            decode_json = data.get('payload')
            
            #take before and after
            before_json = decode_json.get('before')
            after_json = decode_json.get('after')
            
            #take table name
    #             df = pd.DataFrame()
    #             table_name = take_table_name(df)
            table_name_add = table_name[4:]
    
            #Check action
            if(before_json == None and after_json == None):
                continue
            elif (before_json == None):
                list_msg_insert.append(after_json)
                f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Insert.txt", "a", encoding="utf-8")
                for i in cdc_table.index:
                    f.write(f"{after_json}")
                f.close()
            elif (after_json == None):
                list_msg_delete.append(before_json)
                f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Delete.txt", "a", encoding="utf-8")
                for i in cdc_table.index:
                    f.write(f"{after_json}")
                f.close()
            else:
                list_msg_update.append(after_json)
                f = open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Update.txt", "a", encoding="utf-8")
                for i in cdc_table.index:
                    f.write(f"{after_json}")
                f.close()

            meta = consumer.partitions_for_topic(list_topic[0])
            options = {}
            options[TopicPartition(topic=list_topic[0], partition=0)] = OffsetAndMetadata(msg.offset + 1, meta)
            consumer.commit(options)
            if (current_offset >= end_offset or current_offset%50000 == 25000 or is_pk == True):
                if list_msg_insert:
                    insert_data(list_msg_insert,table_name_add,date_col, database_source, engine)
                    with open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Insert.txt",'w') as file:
                        pass
                if list_msg_delete:
                    delete_data(list_msg_delete,table_name_add,date_col, database_source, engine)
                    with open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Delete.txt",'w') as file:
                        pass
                if list_msg_update:
                    update_data(list_msg_update,table_name_add,date_col, database_source, engine)
                    with open(f"CDC_logs\cdc_log_{database_source}_{table_name}_Backup_Update.txt",'w') as file:
                        pass

            if (current_offset >= end_offset or current_offset%50000 == 25000 or is_pk == True):
                break
        #Temporary use try except to avoid bug when read null message
        except:
            is_pk = True
            time.sleep(1)


# In[14]:


if __name__ == "__main__":
    #file directory
    file_dir_ip_and_group = 'Config/config_ip_and_group_id.txt'
    file_dir_dt_col = 'Table/dt_col.txt'
    #file_dir_dc_col = 'Table/dc_col.txt'
    file_dir_config_source = 'Config/config_source.txt'
    file_dir_config_destination = 'Config/config_destination.txt'
    
    #take config source
    username_source, password_source, hostname_source, port_source, database_source, prefix     = take_config_from_file(file_dir_config_source).split('\t')
    
    #take config destination
    username_destination, password_destination, hostname_destination, port_destination, database_destination     = take_config_from_file(file_dir_config_destination).split('\t')
    
    #take config host and group id
    ip_host, group_id = take_config_from_file(file_dir_ip_and_group).split('\t')
    
    #take columns datetime
    date_col = take_dt_col_name_from_file(file_dir_dt_col)
    #take object columns
    #decimal_col = take_dt_col_name_from_file(file_dir_dc_col)
    # Define server with port
    bootstrap_servers = [f'{ip_host}:9092',f'{ip_host}:9093',f'{ip_host}:9094']
    
    #Create process
    file_dir_table = f'Table/cdc_table.txt'
    list_table_name = all_table_name(file_dir_table)
    list_process = {}
    id_process = 0
        
    #create log
    for table_name in list_table_name:
        for action in ['Insert','Update','Delete','Error','Backup_Insert','Backup_Update','Backup_Delete']:
            file_dir_log = f'CDC_logs/cdc_log_{database_source}_{table_name[4:]}_{action}.txt'
            if (os.path.isfile(file_dir_log)) == False:
                f = open(f"{file_dir_log}", "a", encoding="utf-8")
                f.write("Table\tID\tcreate_at\ttype\n")
                f.close()

    #start process

    #while(1):
    for table_name in list_table_name:
        process = Process(target=Consumer, args=(table_name, bootstrap_servers, group_id, prefix, database_source, date_col, username_destination, password_destination, hostname_destination, port_destination, database_destination))
        process.start()
        list_process[id_process] = (process,table_name) #Save the process with it's name
        id_process += 1
        #while(1):
            #if not process.is_alive():
                #print("Prepare next consumer")
                #process.join()
                #break
    
    #Restart dead process
    while len(list_process) > 0:
        for n in list_process.keys():
            (p, t) = list_process[n]
            time.sleep(0.1)
            if not p.is_alive():
                print ('Process Ended with an error or a terminate ', t)
                p.terminate()
                #p.kill()
                #p.join() # Allow tidyup
                p.close()
                process = Process(target=Consumer, args=(t, bootstrap_servers, group_id, prefix, database_source, date_col, username_destination, password_destination, hostname_destination, port_destination, database_destination))
                process.start()
                list_process[n] = (process,t)
                
    print('Finish')

