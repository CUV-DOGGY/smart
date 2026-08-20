from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient


def create_agent_checkpointer(
    mongodb_url: str,
    database_name: str,
) -> MongoDBSaver:
    """Create the checkpoint store with its own synchronous PyMongo client.

    langgraph-checkpoint-mongodb 0.4 exposes async saver methods backed by a
    PyMongo client and runs blocking operations in an executor.  Keeping this
    client separate from Motor also gives the integration a clear lifecycle.
    """
    client = MongoClient(mongodb_url)
    return MongoDBSaver(
        client,
        db_name=database_name,
        checkpoint_collection_name="agent_checkpoints",
        writes_collection_name="agent_checkpoint_writes",
    )
