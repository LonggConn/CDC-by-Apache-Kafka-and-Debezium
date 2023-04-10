USE Customers
GO
EXEC sys.sp_cdc_enable_db
GO
USE Customers
GO
EXEC sys.sp_cdc_enable_table
@source_schema = N'dbo',
@source_name   = N'CustomerDetails', 
@role_name     = null,  
@supports_net_changes = 0
GO
USE Customers
GO 
EXEC sys.sp_cdc_help_change_data_capture 
GO