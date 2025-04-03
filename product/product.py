from flask import Blueprint,Flask,jsonify,request
#!pipenv install flask_restful
from flask_restful import Resource,Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text,DECIMAL
import requests, json

from py_eureka_client import eureka_client
# Kafka
from kafka import KafkaConsumer
# Jaeger configures tracing
from opentelemetry.sdk.resources import Resource as TraceResource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
# run parallel
import threading
import random

# Kafka
# String consumer
# consumer = KafkaConsumer('notification-order',bootstrap_servers='localhost:9092', group_id = 'inventory-consumer')
# JSON format consumer
# consumer = KafkaConsumer('notification-order', # Subscribes to the Kafka topic 'notification-order' to receive messages from it.
#                         bootstrap_servers='localhost:9092', # Connects to a Kafka broker at localhost:9092 to consume messages.
#                         group_id='inventory-consumer', # Assigns the consumer to a group called 'inventory-consumer'. Kafka uses consumer groups to manage message distribution and offset tracking
#                         value_deserializer=lambda x: json.loads(x.decode('utf-8'))) # converts the message payload from bytes to a JSON object using json.loads

# Jeager
resource = TraceResource.create({"service.name" : "product-service"}) # define attributes about the service being traced
trace.set_tracer_provider(TracerProvider(resource=resource)) # acts as the central component for managing tracers and spans across the application.

'''
OTLP stands for OpenTelemetry Protocol, which is a general-purpose telemetry data delivery protocol 
designed as part of the OpenTelemetry project. It defines how telemetry data (like traces, metrics, and logs) 
is encoded, transported, and delivered between sources, intermediate nodes (like collectors), and backends
'''
otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317",insecure=True) # create an OTLPSpanExporter, specifying the endpoint (http://localhost:4317) to which spans will be sent. The insecure=True flag indicates that encryption is not enforced for communication (typically used for local development).

span_processor = BatchSpanProcessor(otlp_exporter) # Adding a span processor
trace.get_tracer_provider().add_span_processor(span_processor)

tracer = trace.get_tracer(__name__) # Acquiring a tracer


PORT=8001
# Eureka register server

# eureka_client.init(eureka_server="http://localhost:8761/eureka", 
#                     app_name="product-service", 
#                     instance_ip ="127.0.0.1", 
#                     instance_port = PORT)

app = Flask(__name__)

# config the connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///product.db'
app.config['SQLALCHEMY_TRACK_MODIFICATION'] = False

# intialize SQLAlchemy
db= SQLAlchemy(app)

api = Api(app)

DISCOVERY_SERVER_URL = 'http://localhost:5000'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(100), nullable = False)
    description = db.Column(db.String(200), nullable = False)
    price = db.Column(db.DECIMAL(precision=10))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": self.price
        }


class ProductResource(Resource):
    global PORT
    def get(self,id=None):
        if id is None:
            # Jaeger Logging and Tracing
            # with tracer.start_as_current_span("get_all_products_span") as span:
            #     # new span as the current active span in the context. The span is named "get_all_products_span"
            #     # custom attributes to the span. These attributes provide additional context for your trace
            #     span.set_attribute("port",PORT)
            #     span.set_attribute("id", random.random())
            #     try:
                
            #         products = Product.query.all()
            #         return jsonify([product.to_dict() for product in products]) 
            #     except:
            #         return {"status": "Failed"}
            try:
                    
                products = Product.query.all()
                return jsonify([product.to_dict() for product in products]) 
            except:
                return {"status": "Failed"}
        else:
            try:
                product = Product.query.get(id)
                if product is None:
                    return  jsonify({"error":"Not found!"})
                return jsonify(product.to_dict())
            except:
                return {"status": "Failed"}

        return {"Method" : "GET"}
    
    def post(self):
        try:
            #payload = request.get_json()
            data = request.json
            name = data["name"]
            description = data["description"]
            price = data["price"]

            print(data)            
            # Create a new product
            new_product = Product(
                name=data['name'],
                description=data['description'],
                price=data['price']
            )

            # Add to the database
            db.session.add(new_product)
            db.session.commit()
            return {"status": "Success", "product" : data} 
        except Exception as e:
            return {"status": "Failed", "Error": str(e)}
        return {"Method" : "POST"}
    
    def put(self,id):
        # Extract data from the request body
        data = request.get_json()

        try:
            # Find the product by ID
            product = Product.query.get(id)
            if not product:
                return jsonify({"error": "Product not found"})

            # Update fields if they are provided in the request
            if 'name' in data:
                product.name = data['name']
            if 'description' in data:
                product.description = data['description']
            if 'price' in data:
                product.price = data['price']

            # Commit the changes to the database
            db.session.commit()
        except:
            return {"status": "Failed"}
        return {"Method" : "PUT"}

    def delete(self,id):
        try:
            # Find the product by ID
            product = Product.query.get(id)
            if not product:
                return jsonify({"error": "Product not found"})

            # Delete the product from the database
            db.session.delete(product)
            db.session.commit()
            return jsonify({"message": f"Product with ID {id} deleted successfully"})
        except:
            return {"status": "Failed"}
        
        return {"Method" : "DEL"}

api.add_resource(ProductResource,'/products','/products/<int:id>')

with app.app_context():
    db.create_all()

def register_service():
    """Register the service with the discovery server."""
    service_info = {
        "name": "product_service",
        "address": "http://localhost:8001"  # Address where this app is running
    }
    try:
        response = requests.post(f"{DISCOVERY_SERVER_URL}/register", json=service_info)
        if response.status_code == 200:
            print("Service registered successfully!")
        else:
            print("Failed to register service:", response.json())
    except Exception as e:
        print("Error registering service:", str(e))

def consume_messages():
    for message in consumer:
        print(message.value)
        consumer.commit() # saves your progress by marking the message as "done." This tells Kafka not to send the same message again if the consumer restarts or reconnects.

if __name__ == "__main__":
    register_service()
    # consume_message() # the issue it hang here so we need to make it run parallel to gether
    # to run parallel (uncomment below code)
    # consumer_thread = threading.Thread(target=consume_messages,daemon=True) # new thread is created // daemon=True ensures that this thread will automatically close when the main program exits.
    # consumer_thread.start() # starts the thread and runs the consume_messages function in the background without blocking the rest of the program.


    app.run(debug=True,host="0.0.0.0",port=PORT)