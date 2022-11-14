clear
python3 train.py --data=/mnt/local0/imagenet_dataset | tee -a log/training.txt

python train.py --data=/home/sathul/Python/ImageNet2012 | tee -a log/training.txt

python train.py --data=/home/sathul/Python/ImageNet2012 --epochs=33
