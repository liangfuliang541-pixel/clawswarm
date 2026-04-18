"""
federated.py — 联邦学习协调器
支持多节点协作训练，不共享原始数据
"""

import json
import time
import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class FLModel:
    """联邦模型定义"""
    model_id: str
    name: str
    version: int
    architecture: str
    params: int
    created_at: float
    aggregation: str = "fed_avg"  # fed_avg, fed_prox, fed_bn


@dataclass
class FLRound:
    """联邦学习轮次"""
    round_id: int
    model_id: str
    started_at: float
    completed_at: Optional[float] = None
    participating_nodes: List[str] = field(default_factory=list)
    global_model_hash: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    status: str = "pending"  # pending, aggregating, completed, failed


class FederatedCoordinator:
    """联邦学习协调器"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._models: Dict[str, FLModel] = {}
        self._rounds: Dict[str, List[FLRound]] = defaultdict(list)
        self._node_updates: Dict[str, Dict[int, Dict]] = defaultdict(lambda: defaultdict(dict))
        self._global_weights: Dict[str, bytes] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._aggregation_hooks: Dict[str, Callable] = {
            "fed_avg": self._aggregate_fed_avg,
            "fed_prox": self._aggregate_fed_prox,
        }
        if storage_path:
            self._load()
    
    def register_model(self, model_id: str, name: str, architecture: str = "nn",
                     params: int = 1000, aggregation: str = "fed_avg") -> FLModel:
        model = FLModel(
            model_id=model_id, name=name, version=1,
            architecture=architecture, params=params,
            created_at=time.time(), aggregation=aggregation,
        )
        with self._lock:
            self._models[model_id] = model
            self._persist()
        return model
    
    def start_round(self, model_id: str, node_ids: List[str]) -> FLRound:
        rounds = self._rounds[model_id]
        round_id = len(rounds) + 1
        fl_round = FLRound(
            round_id=round_id, model_id=model_id,
            started_at=time.time(),
            participating_nodes=node_ids, status="pending",
        )
        with self._lock:
            rounds.append(fl_round)
        return fl_round
    
    def submit_update(self, model_id: str, node_id: str, round_id: int,
                      weights: bytes, num_samples: int,
                      metrics: Optional[Dict] = None) -> bool:
        with self._lock:
            model = self._models.get(model_id)
            if not model:
                return False
            update_hash = hashlib.sha256(weights).hexdigest()
            self._node_updates[model_id][node_id][round_id] = {
                "weights": weights.hex() if isinstance(weights, bytes) else weights,
                "hash": update_hash,
                "num_samples": num_samples,
                "metrics": metrics or {},
                "timestamp": time.time(),
            }
            return True
    
    def complete_round(self, model_id: str, round_id: int) -> Dict:
        with self._lock:
            model = self._models.get(model_id)
            if not model:
                return {"error": f"Model {model_id} not found"}
            rounds = self._rounds[model_id]
            fl_round = next((r for r in rounds if r.round_id == round_id), None)
            if not fl_round:
                return {"error": f"Round {round_id} not found"}
            
            # 获取所有节点更新
            updates = {
                nid: self._node_updates[model_id].get(nid, {}).get(round_id)
                for nid in fl_round.participating_nodes
                if self._node_updates[model_id].get(nid, {}).get(round_id)
            }
            if not updates:
                fl_round.status = "failed"
                return {"error": "No node updates received"}
            
            # 聚合
            agg_func = self._aggregation_hooks.get(model.aggregation, self._aggregate_fed_avg)
            result = agg_func(updates, model.params)
            
            # 保存全局模型
            self._global_weights[model_id] = result["aggregated_weights"]
            fl_round.status = "completed"
            fl_round.completed_at = time.time()
            fl_round.global_model_hash = hashlib.sha256(result["aggregated_weights"]).hexdigest()
            fl_round.metrics = result["metrics"]
            
            self._persist()
            return {
                "model_id": model_id,
                "round_id": round_id,
                "status": "completed",
                "participating_nodes": len(fl_round.participating_nodes),
                "total_samples": result["total_samples"],
                "global_model_hash": fl_round.global_model_hash,
                "metrics": fl_round.metrics,
            }
    
    def get_global_model(self, model_id: str) -> Optional[bytes]:
        return self._global_weights.get(model_id)
    
    def get_model_info(self, model_id: str) -> Optional[Dict]:
        model = self._models.get(model_id)
        if not model:
            return None
        return {
            "model_id": model.model_id, "name": model.name,
            "version": model.version, "architecture": model.architecture,
            "params": model.params, "aggregation": model.aggregation,
            "created_at": model.created_at,
            "completed_rounds": len(self._rounds.get(model_id, [])),
        }
    
    def get_status(self) -> Dict:
        return {
            "models": len(self._models),
            "active_rounds": sum(
                1 for rounds in self._rounds.values()
                for r in rounds if r.status == "pending"
            ),
            "completed_rounds": sum(
                1 for rounds in self._rounds.values()
                for r in rounds if r.status == "completed"
            ),
        }
    
    def _aggregate_fed_avg(self, updates: Dict, num_params: int) -> Dict:
        """联邦平均聚合"""
        total_samples = sum(u["num_samples"] for u in updates.values())
        if total_samples == 0:
            return {"error": "No samples", "aggregated_weights": b"", "metrics": {}}
        
        # 简单的加权平均（十六进制字符串解析）
        weight_sums = [0.0] * num_params
        for update in updates.values():
            try:
                w = bytes.fromhex(update["weights"])
                factor = update["num_samples"] / total_samples
                for i in range(min(len(w), num_params)):
                    weight_sums[i] += w[i] * factor
            except (ValueError, IndexError):
                continue
        
        result_weights = bytes(int(w) & 0xff for w in weight_sums)
        avg_loss = sum(
            u.get("metrics", {}).get("loss", 0) * u["num_samples"]
            for u in updates.values()
        ) / total_samples if updates else 0.0
        
        return {
            "aggregated_weights": result_weights,
            "total_samples": total_samples,
            "num_participants": len(updates),
            "metrics": {"avg_loss": avg_loss},
        }
    
    def _aggregate_fed_prox(self, updates: Dict, num_params: int) -> Dict:
        """FedProx 聚合（简化版：使用上一轮全局模型）"""
        # FedProx 使用服务器端动量，这里简化为加权平均
        return self._aggregate_fed_avg(updates, num_params)
    
    def _persist(self):
        if not self._storage_path:
            return
        try:
            data = {
                "models": [{**m.__dict__} for m in self._models.values()],
                "rounds": {mid: [{**r.__dict__} for r in rounds]
                          for mid, rounds in self._rounds.items()},
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"[Federated] Persist error: {e}")
    
    def _load(self):
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for m in data.get("models", []):
                self._models[m["model_id"]] = FLModel(**m)
            for mid, rounds in data.get("rounds", {}).items():
                for r in rounds:
                    self._rounds[mid].append(FLRound(**r))
            print(f"[Federated] Loaded {len(self._models)} models, "
                  f"{sum(len(rs) for rs in self._rounds.values())} rounds")
        except Exception as e:
            print(f"[Federated] Load error: {e}")
