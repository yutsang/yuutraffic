"""
This is a boilerplate pipeline 'web_app'
generated using Kedro 0.19.14
"""

from kedro.pipeline import Pipeline, node, pipeline  # noqa

from .nodes import load_traffic_data


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=load_traffic_data,
                inputs=None,
                outputs=["routes_df", "stops_df"],
                name="load_traffic_data_node",
            )
        ]
    )
