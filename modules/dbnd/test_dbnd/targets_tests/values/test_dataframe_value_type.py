import attr

from pandas.core.util.hashing import hash_pandas_object

from dbnd._core.utils import json_utils
from dbnd._vendor import fast_hasher
from targets.value_meta import ValueMeta, ValueMetaConf
from targets.values.pandas_values import DataFrameValueType


class TestDataFrameValueType(object):
    def test_df_value_meta(
        self, pandas_data_frame, pandas_data_frame_histograms, pandas_data_frame_stats
    ):
        expected_data_schema = {
            "type": DataFrameValueType.type_str,
            "columns": list(pandas_data_frame.columns),
            "size": int(pandas_data_frame.size),
            "shape": pandas_data_frame.shape,
            "dtypes": {
                col: str(type_) for col, type_ in pandas_data_frame.dtypes.items()
            },
        }

        meta_conf = ValueMetaConf.enabled()
        expected_value_meta = ValueMeta(
            value_preview=DataFrameValueType().to_preview(
                pandas_data_frame, preview_size=meta_conf.get_preview_size()
            ),
            data_dimensions=pandas_data_frame.shape,
            data_schema=expected_data_schema,
            data_hash=fast_hasher.hash(
                hash_pandas_object(pandas_data_frame, index=True).values
            ),
            descriptive_stats=pandas_data_frame_stats,
            histograms=pandas_data_frame_histograms,
        )

        df_value_meta = DataFrameValueType().get_value_meta(
            pandas_data_frame, meta_conf=meta_conf
        )

        assert df_value_meta.value_preview == expected_value_meta.value_preview
        assert df_value_meta.data_hash == expected_value_meta.data_hash
        assert json_utils.dumps(df_value_meta.data_schema) == json_utils.dumps(
            expected_value_meta.data_schema
        )
        assert df_value_meta.data_dimensions == expected_value_meta.data_dimensions

        std = df_value_meta.descriptive_stats["Births"].pop("std")
        expected_std = expected_value_meta.descriptive_stats["Births"].pop("std")
        assert round(std, 2) == expected_std
        df_value_meta.descriptive_stats["Names"].pop("top")
        assert df_value_meta.descriptive_stats == expected_value_meta.descriptive_stats

        counts, values = df_value_meta.histograms.pop("Names")
        expected_counts, expected_values = expected_value_meta.histograms.pop("Names")
        assert counts == expected_counts
        assert set(values) == set(expected_values)  # order changes in each run
        # histograms are tested in histogram tests and they change a lot, no need to test also here
        df_value_meta.histograms = expected_value_meta.histograms = None

        expected_value_meta.histogram_system_metrics = (
            df_value_meta.histogram_system_metrics
        )
        assert df_value_meta.data_schema == expected_value_meta.data_schema
        assert attr.asdict(df_value_meta) == attr.asdict(expected_value_meta)
