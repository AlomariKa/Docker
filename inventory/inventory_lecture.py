'''
    Inenvtory:
        id
        skucode
        quantity
        

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
from opentelemetry.propagate import get_global_textmap

import random

resource = TraceResource.create({"service.name" : "inventory-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))

otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317",insecure=True)

span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

tracer = trace.get_tracer(__name__)


PORT = 8003
eureka_client.init(eureka_server="http://localhost:8761/eureka",
                    app_name="inventory-service",
                    instance_ip ="127.0.0.1",
                    instance_port = PORT)

app = Flask(__name__)

# config the connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATION'] = False

# intialize SQLAlchemy
db= SQLAlchemy(app)

api = Api(app)


class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    skuCode = db.Column(db.String(100), nullable = False)
    quantity = db.Column(db.Integer, nullable = True)


    def to_dict(self):
        return {
            "id": self.id,
            "skuCode": self.skuCode,
            "quantity": self.quantity
        }


class InventoryResource(Resource):
    global PORT
    def get(self,id=None):
        if id is None:
            try:
                inventory = Inventory.query.all()
                headers = request.headers
                context = get_global_textmap().extract(headers)
                with tracer.start_as_current_span("check_inventory_span",context=context) as span:
                    span.set_attribute("id",PORT)
                return [inventory_line.to_dict() for inventory_line in inventory]
            except:
                return {"status": "Failed"}
        else:
            try:
                inventory_line = Inventory.query.get(id)
                if inventory_line is None:
                    return  jsonify({"error":"Not found!"})
                return jsonify(inventory_line.to_dict())
            except:
                return {"status": "Failed"}

        return {"Method" : "GET"}
    
    def post(self):
        try:
            #payload = request.get_json()
            data = request.json
            skuCode = data["skuCode"]
            quantity = data["quantity"]
          
            # Create a new product
            new_inventory_line = Inventory(
                skuCode=data['skuCode'],
                quantity=data['quantity'],
            )

            # Add to the database
            db.session.add(new_inventory_line)
            db.session.commit()
            return {"status": "Success", "inventoryLine" : data} 
        except Exception as e:
            return {"status": "Failed", "Error": str(e)}
        return {"Method" : "POST"}
    
    def put(self,id):
        # Extract data from the request body
        data = request.get_json()

        try:
            # Find the product by ID
            inventory_line = inventory.query.get(id)
            if not inventory_line:
                return jsonify({"error": "Product not found"})

            # Update fields if they are provided in the request
            if 'skuCode' in data:
                inventory_line.skuCode = data['skuCode']
            if 'description' in data:
                inventory_line.quantity = data['quantity']

            # Commit the changes to the database
            db.session.commit()
        except:
            return {"status": "Failed"}
        return {"Method" : "PUT"}

    def delete(self,id):
        try:
            # Find the product by ID
            inventory_line = inventory.query.get(id)
            if not product:
                return jsonify({"error": "Product not found"})

            # Delete the product from the database
            db.session.delete(inventory_line)
            db.session.commit()
            return jsonify({"message": f"Product with ID {id} deleted successfully"})
        except:
            return {"status": "Failed"}
        
        return {"Method" : "DEL"}

api.add_resource(InventoryResource,'/inventory','/inventory/<int:id>')

with app.app_context():
    db.create_all()



if __name__ == "__main__":

    
    # # Register the application with Eureka
    # eureka_client.start()

    app.run(debug=True,port=8003)