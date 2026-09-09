MobileNet v2-12, ONNX Model Zoo, Apache 2.0 (voir LICENSE.txt).
Source : https://github.com/onnx/models/tree/main/validated/vision/classification/mobilenet
Poids : https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx

Le modèle est fourni avec le logiciel : aucun téléchargement au lancement.
Prétraitement RGB 224x224, moyenne 0.485/0.456/0.406 et écart-type 0.229/0.224/0.225.
Reconnaissance initiale de catégories ImageNet traduites en français (voir image_content.py).
Il classe surtout le sujet dominant, ne détecte pas tous les objets d'une scène et peut manquer des sujets petits ou atypiques. Les étiquettes sont des suggestions, pas des certitudes.
