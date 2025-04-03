'''
    Product:
        id
        name
        description
        price

'''

from flask import Blueprint,Flask,jsonify,request
#!pipenv install flask_restful
from flask_restful import Resource,Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text,DECIMAL
from py_eureka_client import eureka_client

from opentelemetry.sdk.resources import Resource as TraceResource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import threading

import random
from kafka import KafkaConsumer

consumer = KafkaConsumer('notification-order',
                        bootstrap_servers='localhost:9092',
                        group_id='invetory-consumer',
                        value_deserializer=lambda x: json.loads(x.decode('utf-8')))

resource = TraceResource.create({"service.name" : "product-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))

otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317",insecure=True)

span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

tracer = trace.get_tracer(__name__)

PORT = 8001
eureka_client.init(eureka_server="http://localhost:8761/eureka",
                    app_name="product-service",
                    instance_ip ="127.0.0.1",
                    instance_port = PORT)


app = Flask(__name__)

# config the connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///product.db'
app.config['SQLALCHEMY_TRACK_MODIFICATION'] = False

# intialize SQLAlchemy
db= SQLAlchemy(app)

api = Api(app)


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
            with tracer.start_as_current_span("get_all_products_span") as span:
                span.set_attribute("port",PORT )
                span.set_attribute("id", random.random())
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

def consume_messages():
    for message in consumer:
        print(message.value.decode('utf-8'))

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    consumer_thread = threading.Thread(target=consume_messages,daemon=True)
    consumer_thread.start()

    app.run(debug=True,port=PORT)