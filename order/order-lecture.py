'''
    Order:
        id
        skuCode
        price
        quantity
'''
from flask import Blueprint,Flask,jsonify,request
#!pipenv install flask_restful
from flask_restful import Resource,Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text,DECIMAL
import requests
from py_eureka_client import eureka_client
import json
import xml.etree.ElementTree as ET
import logging

from opentelemetry.sdk.resources import Resource as TraceResource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.propagate import get_global_textmap

import random
from kafka import KafkaProducer





resource = TraceResource.create({"service.name" : "order-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))

otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317",insecure=True)

span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

tracer = trace.get_tracer(__name__)

PORT = 8002

logging.basicConfig(level=logging.INFO)

eureka_client.init(eureka_server="http://localhost:8761/eureka",
                    app_name="order-service",
                    instance_ip ="127.0.0.1",
                    instance_port = PORT)


app = Flask(__name__)

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
                return {"status": "Failed"}

        return {"Method" : "GET"}
    
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

                #Configuration
                producer = KafkaProducer(bootstrap_servers='localhost:9092',
                                        value_serializer=lambda v: json.dumps(v).encode('utf-8'))
                # Send a message to a topic
                # producer.send('notification-order',f"Order succesfully for {skuCode} with {quantity} units".encode('utf-8'))

                my_order_object = {
                    "skuCode": skuCode,
                    "quantity": quantity,
                    "price": price
                } 
                producer.send('notification-order',value=my_order_object)

                # block until all messages are sent
                producer.flush()
                producer.close()

                return {"status": "Success", "orderLine" : data} 
            else:
                 return {"status": "Out of stock"}            
        except Exception as e:
            return {"status": "Failed", "Error": str(e)}
        return {"Method" : "POST"}
    
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
            return {"status": "Failed"}
        return {"Method" : "PUT"}

    def delete(self,id):
        try:
            # Find the product by ID
            order_line = Order.query.get(id)
            if not product:
                return jsonify({"error": "Product not found"})

            # Delete the product from the database
            db.session.delete(order_line)
            db.session.commit()
            return jsonify({"message": f"Product with ID {id} deleted successfully"})
        except:
            return {"status": "Failed"}
        
        return {"Method" : "DEL"}

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


def checkInventory(skuCode,quantity):
    global lastRequest
    global PORT
    try:
        ''' static url http requests '''
        '''
            service_invetory_url = "http://localhost:8003/inventory"
            response = requests.get(service_invetory_url)
            response.raise_for_status()
            inventory = response.json()
        '''
        '''
            This is simple Eureka request
        '''
        headers = {}
        with tracer.start_as_current_span("check_order_span") as span:
            span.set_attribute("id", PORT)
            get_global_textmap().inject(headers)

            response = eureka_client.do_service(
                    app_name="INVENTORY-SERVICE",
                    service = "/inventory",
                    headers = headers)
            inventory = json.loads(response)
        
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

        found = False
        for item in inventory:
            #print(skuCode,item["skuCode"],item["quantity"]-quantity)
            if skuCode == item["skuCode"] and item["quantity"] - quantity >= 0:
                found = True

        return found
    except Exception as e:
        print(str(e))
        return False


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True,port=8002)