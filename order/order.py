from flask import Blueprint,Flask,jsonify,request
#!pipenv install flask_restful
from flask_restful import Resource,Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text,DECIMAL
import requests, json
from py_eureka_client import eureka_client
import xml.etree.ElementTree as ET
import logging
from opentelemetry.propagate import get_global_textmap
# Kafka
from kafka import KafkaProducer
# Jaeger configures tracing
from opentelemetry.sdk.resources import Resource as TraceResource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import random
# Circuit breaker
import pybreaker

# Circuit breaker Config
import pybreaker

# Initialize the Circuit Breaker with settings
breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=10)  # Allow 3 failures before "breaking" and wait 10 seconds to reset


# Jeager Config
resource = TraceResource.create({"service.name" : "order-service"}) 
trace.set_tracer_provider(TracerProvider(resource=resource)) 


otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317",insecure=True) 

span_processor = BatchSpanProcessor(otlp_exporter) 
trace.get_tracer_provider().add_span_processor(span_processor)

tracer = trace.get_tracer(__name__) 


app = Flask(__name__)

PORT=8002

logging.basicConfig(level=logging.INFO) # log messages for debugging, monitoring, and tracking the behavior of your program.
# Eureka register server
# provides functionality for registering services with a Eureka Server and discovering other services
# eureka_client.init(eureka_server="http://localhost:8761/eureka", # Specifies the URL of the Eureka Server where the service will register itself.
#                     app_name="order-service", # Sets the name of the application or service being registered. Other services will use this name to discover it.
#                     instance_ip ="127.0.0.1", # Specifies the IP address of the instance being registered (here, it's localhost)
#                     instance_port = PORT) # Specifies the port number on which this service is running.
# The init method is used to configure the service and register it with the Eureka Server


# Discovery server URL
DISCOVERY_SERVER_URL = 'http://localhost:5000'
# config the connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///order.db'
app.config['SQLALCHEMY_TRACK_MODIFICATION'] = False

# intialize SQLAlchemy
db= SQLAlchemy(app)

api = Api(app)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    skuCode = db.Column(db.String(100), nullable = False)
    price = db.Column(db.DECIMAL(precision=10))
    quantity = db.Column(db.Integer, nullable = True)


    def to_dict(self):
        return {
            "id": self.id,
            "skuCode": self.skuCode,
            "price": self.price,
            "quantity": self.quantity
        }


class OrderResource(Resource):

    def get(self,id=None):
        if id is None:
            try:
               order = Order.query.all()
               return jsonify([order_line.to_dict() for order_line in order]) 
            except:
                return {"status": "Failed"}
        else:
            try:
                order_line = Order.query.get(id)
                if order_line is None:
                    return  jsonify({"error":"Not found!"})
                return jsonify(order_line.to_dict())
            except:
                return {"status": "Failed GET"}

    
    
             
    def post(self):
        try:
            #payload = request.get_json()
            data = request.json
            skuCode = data["skuCode"]
            quantity = data["quantity"]
            price = data["price"]
            if checkInventory(skuCode,quantity):
                # Create a new product
                new_order_line = Order(
                    skuCode=data['skuCode'],
                    quantity=data['quantity'],
                    price=data['price']
                )

                # Add to the database
                db.session.add(new_order_line)
                db.session.commit()

                # Congiguration Kafka
                # send string
                # producer = KafkaProducer(bootstrap_servers='localhost:9092')
                # send JSON
                # producer = KafkaProducer(bootstrap_servers='localhost:9092',
                #                         value_serializer=lambda v: json.dumps(v).encode('utf-8')) # json.dumps(v) to convert the object v into a JSON string and then encodes it into bytes (.encode('utf-8')) since Kafka expects messages to be in byte format.

                # Send a message to a topic
                # send String
                # producer.send('notification-order',f"Order succesfully for {skuCode} with {quantity} units".encode('utf-8'))
                # send JSON
                # my_order_object = {
                #     "skuCode": skuCode,
                #     "quantity": quantity,
                #     "price": price
                # } 
                # producer.send('notification-order',value=my_order_object)

                # # block until all messages are sent
                # producer.flush() # makes sure all pending data reaches the Kafka server.
                # producer.close() # The producer is safely shut down.

                return {"status": "Success", "orderLine" : data} 
            else:
                 return {"status": "Out of stock"}  
        except pybreaker.CircuitBreakerError:
            return {"status": "Service unavailable. Please try again later."}, 503          
        except Exception as e:
            return {"status": "Failed POST", "Error": str(e)}
        
    def put(self,id):
        # Extract data from the request body
        data = request.get_json()

        try:
            # Find the product by ID
            order_line = Order.query.get(id)
            if not order_line:
                return jsonify({"error": "Product not found"})

            # Update fields if they are provided in the request
            if 'skuCode' in data:
                order_line.skuCode = data['skuCode']
            if 'quantity' in data:
                order_line.quantity = data['quantity']
            if 'price' in data:
                order_line.price = data['price']

            # Commit the changes to the database
            db.session.commit()
        except:
            return {"status": "Failed PUT"}
        return {"Method" : "PUT"}

    def delete(self,id):
        try:
            # Find the order by ID
            order_line = Order.query.get(id)
            if not order_line:
                return jsonify({"error": "Product not found"})

            # Delete the product from the database
            db.session.delete(order_line)
            db.session.commit()
            return jsonify({"message": f"Product with ID {id} deleted successfully"})
        except:
            return {"status": "Failed Delete"}
        

api.add_resource(OrderResource,'/orders','/orders/<int:id>')



lastRequest = True

def loadbalancing():
    key =  True
    try:
        response = requests.get("http://localhost:8761/eureka/apps/INVENTORY-SERVICE")
        response.raise_for_status()
        data = ET.fromstring(response.text)
        ipAddresses =  {}
        for instance in data.findall(".//instance"):
            app_name = instance.find("app").text
            ipAddr  = instance.find("ipAddr").text
            port  = instance.find("port").text
            # ipAddresses.append("http://" + ipAddr + ":" + port + "/" )
            ipAddresses[key] = "http://" + ipAddr + ":" + port + "/"
            key = not key
        return ipAddresses
    except Exception as e:
        print(e)
        print("Fetch unsuccessful!")
        return  None
@breaker
def checkInventory(skuCode,quantity):
    global lastRequest
    global PORT
    try:
        logging.info("Attempting inventory check...")
        ''' Static url http requests '''
        
        service_invetory_url = "http://localhost:8003/inventory"
        response = requests.get(service_invetory_url) # GET method .get
        response.raise_for_status()  # Raises an exception if the HTTP request returned an error (4xx/5xx).
        inventory = response.json()  # Parses the JSON and converts it into a Python dictionary or list response and stores it in the `inventory` variable.
        
        
        
        ''' Using Flask Discovery Server '''
        # inventory_address = requests.get(f"{DISCOVERY_SERVER_URL}/discover/inventory_service")
        # response = requests.get(f"{inventory_address.json()}/inventory") # GET method .get

        ''' Extract Ip address and port from Eureka request''' 
        # ip_address,port = discover_inventory_service()
        # response = requests.get(f"http://{ip_address}:{port}/inventory") # GET method .get
        # response.raise_for_status()  # Raises an exception if the HTTP request returned an error (4xx/5xx).
        # inventory = response.json()  # Parses the JSON and converts it into a Python dictionary or list response and stores it in the `inventory` variable.

        ''' Using Simple Eureka request''' 
        # response = eureka_client.do_service("INVENTORY-SERVICE","/inventory")
        # inventory = json.loads(response)

        '''
            Add load balancing
        '''
        # ipAddresses = loadbalancing()
 
        # if ipAddresses is None:
        #     return False
        # service_invetory_url = ipAddresses[lastRequest] + "inventory"
        # print(service_invetory_url)
        # response = requests.get(service_invetory_url)
        # response.raise_for_status()
        # inventory = response.json()
        # lastRequest = not lastRequest

        ''' Using tracing and spans''' 
        # headers = {}
        # with tracer.start_as_current_span("check_order_span") as span:
        #     span.set_attribute("id", PORT)
        #     get_global_textmap().inject(headers)
        #     response = eureka_client.do_service(
        #         app_name="INVENTORY-SERVICE",
        #         service="/inventory", # specific endpoint
        #         headers=headers) # do_service function essentially sends an HTTP request to a service that has been registered with Eureka
        #     # response = eureka_client.do_service("INVENTORY-SERVICE","/inventory")
        #     inventory = json.loads(response) # json module that parses (reads) a JSON-formatted string and converts it into a corresponding Python object, such as a dictionary or a list.
        '''
            the use of json.loads() suggests that the response from eureka_client.do_service is a JSON string. 
            
            If it were an HTTP response object with JSON content, you would typically use response.json() instead
        
        '''
       

        
    
        found = False
        for item in inventory:
            if skuCode == item["skuCode"] and item["quantity"]- quantity >=0:
                found = True
        return found
    except Exception as e:
        logging.error(f"CheckInventory Error: {e}")
        print(f"Error from Check inventory: {e}")
        raise


with app.app_context():
    db.create_all()

import requests
# allows you to parse and manipulate XML data. It is useful for traversing an XML structure and extracting the required elements.
def discover_inventory_service():
    eureka_server = "http://localhost:8761/eureka"
    app_name = "inventory-service"
    
    try:
        # Send a GET request to the Eureka server
        # ./apps/ endpoint provide by Eureka is used to retrieve information about all registered applications.
        response = requests.get(f"{eureka_server}/apps/{app_name}")
        
        if response.status_code == 200:
            # You can create custom tags
            root = ET.fromstring(response.text) # .text output the raw response from the server 
            print(response.text)
            # ET.fromstring() method parses the input string (which contains the XML data) and converts it into an XML tree structure
            # Extract IP address and port
            ip_address = root.find(".//ipAddr").text  # Find the IP address element
            # .find() method is used to locate the <ipAddr> element within the XML structure. 
            # The XPath-like expression .//ipAddr searches for the <ipAddr> tag anywhere under the root element.
            # .text accesses the content inside the <ipAddr> tag
            port = root.find(".//port").text  # Find the port element
            
            return ip_address ,port
        else:
            return f"Failed to discover service. Status code: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"



def register_service():
    """Register the service with the discovery server."""
    service_info = {
        "name": "order_service",
        "address": "http://localhost:8002"  # Address where this app is running
    }
    try:
        response = requests.post(f"{DISCOVERY_SERVER_URL}/register", json=service_info)
        if response.status_code == 200:
            print("Service registered successfully!")
        else:
            print("Failed to register service:", response.json())
    except Exception as e:
        print("Error registering service:", str(e))
if __name__ == "__main__":
    register_service()
    app.run(debug=True,host='0.0.0.0',port=PORT)