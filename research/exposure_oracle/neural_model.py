"""Small supervised network, explicit temporal validation and safe JSON inference."""
from copy import deepcopy
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True,extra='forbid')
    train_end: str = '2012-12-31'
    validation_end: str = '2015-12-31'
    seed: int = 17
    epochs: int = Field(default=400,ge=1,le=400)
    patience: int = Field(default=40,ge=1,le=400)


def finite_matrix(x: np.ndarray) -> np.ndarray:
    value = np.asarray(x,dtype=float)
    if value.ndim != 2 or not len(value) or not np.isfinite(value).all():
        raise ValueError('nonempty finite feature matrix required')
    return value


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True,extra='forbid',allow_inf_nan=False)
    schema_version: Literal['sentinel-neural-imitation/1'] = 'sentinel-neural-imitation/1'
    features: list[str]
    mean: list[float]
    scale: list[float]
    weights: list[list[list[float]]]
    biases: list[list[float]]
    actions: list[float] = Field(default_factory=lambda:[0.,.55,1.])
    metadata: dict

    @model_validator(mode='after')
    def dimensions(self):
        width = len(self.features)
        if (width == 0 or len(set(self.features)) != width or
                len(self.mean) != width or len(self.scale) != width or
                any(s <= 0 for s in self.scale) or self.actions != [0.,.55,1.] or
                len(self.weights) != 3 or len(self.biases) != 3):
            raise ValueError('model feature/action/scale contract changed')
        for weights,biases in zip(self.weights,self.biases):
            matrix = np.asarray(weights,dtype=float)
            if matrix.ndim != 2 or matrix.shape != (width,len(biases)) or not len(biases):
                raise ValueError('model layer shapes changed')
            width = len(biases)
        if width != 3:
            raise ValueError('model requires three output actions')
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        values = finite_matrix(x)
        if values.shape[1] != len(self.features):
            raise ValueError('feature order/dimension mismatch')
        return np.clip((values-np.asarray(self.mean))/np.asarray(self.scale),-5,5)

    def probabilities(self, x: np.ndarray) -> np.ndarray:
        values = self.transform(x)
        for i,(weight,bias) in enumerate(zip(self.weights,self.biases)):
            values = values@np.asarray(weight)+np.asarray(bias)
            if i < len(self.weights)-1:
                values = np.tanh(values)
        values = np.exp(values-values.max(axis=1,keepdims=True))
        probabilities = values/values.sum(axis=1,keepdims=True)
        if not np.isfinite(probabilities).all():
            raise ValueError('nonfinite network probabilities')
        return probabilities

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.probabilities(x).argmax(axis=1)


def scaler(x: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    values = finite_matrix(x)
    mean,scale = values.mean(axis=0),values.std(axis=0)
    scale = np.where(scale < 1e-12,1.,scale)
    return mean,scale


def cross_entropy(labels: np.ndarray, probabilities: np.ndarray) -> float:
    labels = np.asarray(labels,dtype=int)
    p = finite_matrix(probabilities)
    if len(labels) != len(p) or p.shape[1] != 3 or not np.isin(labels,[0,1,2]).all():
        raise ValueError('invalid label/probability shape')
    if (p < 0).any() or not np.allclose(p.sum(axis=1),1,rtol=0,atol=1e-12):
        raise ValueError('invalid probability distribution')
    return float(-np.log(np.maximum(p[np.arange(len(labels)),labels],1e-15)).mean())


def classifier(settings: Settings):
    from sklearn.neural_network import MLPClassifier
    return MLPClassifier(hidden_layer_sizes=(16,8),activation='tanh',solver='adam',
        alpha=.01,batch_size=64,learning_rate_init=.001,max_iter=1,
        random_state=settings.seed,shuffle=True,early_stopping=False)


def freeze(estimator, names: list[str], mean: np.ndarray, scale: np.ndarray, metadata: dict) -> FrozenModel:
    if estimator.classes_.tolist() != [0,1,2]:
        raise ValueError('fitted output class order changed')
    return FrozenModel(features=names,mean=mean.tolist(),scale=scale.tolist(),
        weights=[w.tolist() for w in estimator.coefs_],biases=[b.tolist() for b in estimator.intercepts_],
        metadata=metadata)


def select(x_train, y_train, x_validation, y_validation, names, settings: Settings, metadata: dict):
    # Deliberately has no test arguments. Scaling is learned from training only.
    mean,scale = scaler(x_train)
    train = np.clip((finite_matrix(x_train)-mean)/scale,-5,5)
    validation = np.clip((finite_matrix(x_validation)-mean)/scale,-5,5)
    estimator = classifier(settings)
    best_loss,best_epoch,best,history = float('inf'),0,None,[]
    for epoch in range(1,settings.epochs+1):
        estimator.partial_fit(train,y_train,classes=np.arange(3))
        loss = cross_entropy(y_validation,estimator.predict_proba(validation))
        history.append(dict(epoch=epoch,train_cross_entropy=cross_entropy(y_train,estimator.predict_proba(train)),
                            validation_cross_entropy=loss))
        if loss < best_loss-1e-6:
            best_loss,best_epoch,best = loss,epoch,deepcopy(estimator)
        if epoch-best_epoch >= settings.patience:
            break
    if best is None:
        raise ValueError('no finite validation checkpoint')
    model = freeze(best,list(names),mean,scale,dict(**metadata,selected_epoch=best_epoch))
    if not np.allclose(model.probabilities(x_validation),best.predict_proba(validation),rtol=0,atol=1e-12):
        raise ValueError('exported inference differs from fitted network')
    return model,history


def refit(x, y, names, settings: Settings, epochs: int, metadata: dict) -> FrozenModel:
    if not 1 <= epochs <= settings.epochs:
        raise ValueError('refit epochs must be fixed by completed validation')
    mean,scale = scaler(x)
    transformed = np.clip((finite_matrix(x)-mean)/scale,-5,5)
    estimator = classifier(settings)
    for _ in range(epochs):
        estimator.partial_fit(transformed,y,classes=np.arange(3))
    model = freeze(estimator,list(names),mean,scale,dict(**metadata,selected_epoch=epochs))
    if not np.allclose(model.probabilities(x),estimator.predict_proba(transformed),rtol=0,atol=1e-12):
        raise ValueError('refit export differs from fitted network')
    return model


def classification(labels, probabilities) -> dict:
    labels = np.asarray(labels,dtype=int)
    predicted = np.asarray(probabilities).argmax(axis=1)
    matrix = np.zeros((3,3),dtype=int)
    np.add.at(matrix,(labels,predicted),1)
    recalls = [float(matrix[i,i]/matrix[i].sum()) if matrix[i].sum() else None for i in range(3)]
    return dict(accuracy=float(np.mean(labels == predicted)),cross_entropy=cross_entropy(labels,probabilities),
        confusion=matrix.tolist(),recall=recalls,
        balanced_accuracy=float(np.mean([r for r in recalls if r is not None])))
