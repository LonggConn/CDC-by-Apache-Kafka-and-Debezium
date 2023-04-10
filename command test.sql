use Customers
go
update dbo.CustomerDetails
set gender = 'Male'
where id = '1'
go
update dbo.CustomerDetails
set gender = 'Female'
where id = '6'
go
delete from CustomerDetails where id = '19'
go
INSERT INTO CustomerDetails(id,first_name,last_name,email,gender, ip_address) 
VALUES ('19','Nikolia','Alesin','nalesini@hugedomains.com','Female','54.247.55.206'); 