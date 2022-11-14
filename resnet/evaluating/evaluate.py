import os
import sys
import shutil
import numpy as np
import time, datetime
import torch
import random
import logging
import argparse
import torch.nn as nn
import torch.utils
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.utils.data.distributed

sys.path.append("../../")
from utils.utils import *
from torchvision import datasets, transforms
from torch.autograd import Variable
from resnet import ResNet50

parser = argparse.ArgumentParser("ResNet50")
parser.add_argument('--batch_size', type=int, default=512, help='batch size')
parser.add_argument('--epochs', type=int, default=320, help='num of training epochs')
parser.add_argument('--learning_rate', type=float, default=0.2, help='init learning rate')
parser.add_argument('--momentum', type=float, default=0.9, help='momentum')
parser.add_argument('--weight_decay', type=float, default=1e-4, help='weight decay')
parser.add_argument('--save', type=str, default='./models_V2R1N3', help='path for saving trained models')
parser.add_argument('--data', metavar='DIR', help='path to dataset')
parser.add_argument('--label_smooth', type=float, default=0.1, help='label smoothing')
parser.add_argument('--train_print_freq', type=float, default=100, help='report frequency')
parser.add_argument('--val_print_freq', type=float, default=10, help='report frequency')
parser.add_argument('-j', '--workers', default=40, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
args = parser.parse_args()

CLASSES = 1000

os.environ["CUDA_VISIBLE_DEVICES"] = '2,3'
print("Using GPU No:", os.environ["CUDA_VISIBLE_DEVICES"])

# if not os.path.exists('log'):
#     os.mkdir('log')

#define the format of the log file.
# log_format = '%(asctime)s %(message)s'
# logging.basicConfig(stream=sys.stdout, level=logging.INFO,
#     format=log_format, datefmt='%m/%d %I:%M:%S %p')
# fh = logging.FileHandler(os.path.join('log/log.txt'))
# fh.setFormatter(logging.Formatter(log_format))
# logging.getLogger().addHandler(fh)

def main():
    if not torch.cuda.is_available():
        sys.exit(1)

    cudnn.benchmark = True
    cudnn.enabled=True
    # logging.info("args = %s", args)

    # Loading the Network Encoding Vector
    # network_encoding_vector = [19, 9, 15, 13, 10, 9, 10, 6, 9, 13, 11, 12, 7, 18, 7, 13, 12, 10, 19, 18]              # Default
    # network_encoding_vector = [20, 28, 21, 15, 11, 15, 21, 20, 12, 24, 16, 22, 20, 18, 19, 22, 15, 23, 22, 22]        # V1 No1
    network_encoding_vector = [14, 14, 16, 22, 21, 22, 20, 19, 16, 22, 16, 20, 22, 12, 25, 18, 15, 21, 21, 21]        # V2 No3
    # network_encoding_vector = [17, 17, 22, 16, 23, 14, 16, 21, 17, 19, 19, 20, 19, 16, 21, 22, 13, 22, 10, 23]        # v3 No2
    
    # load model
    model = ResNet50(network_encoding_vector)
    # logging.info(model)
    model = nn.DataParallel(model).cuda()

    criterion = nn.CrossEntropyLoss()
    criterion = criterion.cuda()
    criterion_smooth = CrossEntropyLabelSmooth(CLASSES, args.label_smooth)
    criterion_smooth = criterion_smooth.cuda()

    # split the weight parameter that need weight decay
    all_parameters = model.parameters()
    weight_parameters = []
    for pname, p in model.named_parameters():
        if 'fc' in pname or 'conv' in pname:
            weight_parameters.append(p)
    weight_parameters_id = list(map(id, weight_parameters))
    other_parameters = list(filter(lambda p: id(p) not in weight_parameters_id, all_parameters))

    # define the optimizer
    optimizer = torch.optim.SGD(
        [{'params' : other_parameters},
        {'params' : weight_parameters, 'weight_decay' : args.weight_decay}],
        args.learning_rate,
        momentum=args.momentum,
        )

    # define the learning rate scheduler
    # we use the linear learning rate here
    #scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step : (1.0-step/args.epochs), last_epoch=-1)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=[args.epochs//4, args.epochs//2, args.epochs//4*3], gamma=0.1)
    start_epoch = 0
    best_top1_acc= 0

    # load the checkpoint if it exists
    checkpoint_tar = os.path.join(args.save, 'checkpoint.pth.tar')
    if os.path.exists(checkpoint_tar):
        logging.info('loading checkpoint {} ..........'.format(checkpoint_tar))
        checkpoint = torch.load(checkpoint_tar)
        start_epoch = checkpoint['epoch'] + 1
        best_top1_acc = checkpoint['best_top1_acc']
        model.load_state_dict(checkpoint['state_dict'])
        logging.info("loaded checkpoint {} epoch = {}" .format(checkpoint_tar, checkpoint['epoch']))

    # adjust the learning rate according to the checkpoint
    for epoch in range(start_epoch):
        scheduler.step()

    # load training data
    traindir = os.path.join(args.data, 'ILSVRC2012_img_train')
    valdir = os.path.join(args.data, 'ILSVRC2012_img_val')
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])

    # data augmentation
    crop_scale = 0.08
    lighting_param = 0.1
    train_transforms = transforms.Compose([
        transforms.RandomResizedCrop(224, scale=(crop_scale, 1.0)),
        Lighting(lighting_param),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        normalize])

    train_dataset = datasets.ImageFolder(
        traindir,
        transform=train_transforms)

    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, pin_memory=True)

    # load validation data
    val_loader = torch.utils.data.DataLoader(
        datasets.ImageFolder(valdir, transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            normalize,
        ])),
        batch_size=args.batch_size, shuffle=False,
        num_workers=args.workers, pin_memory=True)

    # train the model
    epoch = start_epoch
    while epoch < args.epochs:
        start_time = time.time()
        
        train_obj, train_top1_acc,  train_top5_acc = train(epoch,  train_loader, model, criterion_smooth, optimizer, scheduler)
        valid_obj, valid_top1_acc, valid_top5_acc = validate(epoch, val_loader, model, criterion, args)
        print('\nEpoch {}:-\nTraining: Top-1 Accuracy = {:.3f} and Top-5 Accuracy = {:.3f}'.format(epoch, train_top1_acc, train_top5_acc))
        print('Validation: Top-1 Accuracy = {:.3f} and Top-5 Accuracy = {:.3f}'.format(valid_top1_acc, valid_top5_acc))

        is_best = False
        if valid_top1_acc > best_top1_acc:
            best_top1_acc = valid_top1_acc
            is_best = True

        if is_best:
            print("Best Model yet!!!")

        save_checkpoint({
            'epoch': epoch,
            'state_dict': model.state_dict(),
            'best_top1_acc': best_top1_acc,
            'optimizer' : optimizer.state_dict(),
            }, is_best, args.save)

        epoch += 1
        now_time = time.gmtime(time.time() - start_time)
        print('Evaluation took {} hours {} mins and {} secs\n\n'.format(now_time.tm_hour, now_time.tm_min, now_time.tm_sec))


def train(epoch, train_loader, model, criterion, optimizer, scheduler):
    batch_time = AverageMeter('Time', ':6.3f')
    data_time = AverageMeter('Data', ':6.3f')
    losses = AverageMeter('Loss', ':.4e')
    top1 = AverageMeter('Acc@1', ':6.2f')
    top5 = AverageMeter('Acc@5', ':6.2f')

    progress = ProgressMeter(
        len(train_loader),
        [batch_time, data_time, losses, top1, top5],
        prefix="Epoch: [{}]".format(epoch))

    model.train()
    end = time.time()
    scheduler.step()

    cur_lr = 0.0000000000002
    for param_group in optimizer.param_groups:
        param_group['lr'] = cur_lr
    print('Learing Rate:', cur_lr)

    
    # for param_group in optimizer.param_groups:
    #     cur_lr = param_group['lr']
    # print('learning_rate:', cur_lr)
    
    for i, (images, target) in enumerate(train_loader):
        data_time.update(time.time() - end)
        images = images.cuda()
        target = target.cuda()

        # compute output
        logits = model(images)
        loss = criterion(logits, target)

        # measure accuracy and record loss
        prec1, prec5 = accuracy(logits, target, topk=(1, 5))
        n = images.size(0)
        losses.update(loss.item(), n)   #accumulated loss
        top1.update(prec1.item(), n)
        top5.update(prec5.item(), n)

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        # if i % args.train_print_freq == 0:
        #     progress.display(i)

    return losses.avg, top1.avg, top5.avg


def validate(epoch, val_loader, model, criterion, args):
    batch_time = AverageMeter('Time', ':6.3f')
    losses = AverageMeter('Loss', ':.4e')
    top1 = AverageMeter('Acc@1', ':6.2f')
    top5 = AverageMeter('Acc@5', ':6.2f')
    progress = ProgressMeter(
        len(val_loader),
        [batch_time, losses, top1, top5],
        prefix='Test: ')

    # switch to evaluation mode
    model.eval()
    with torch.no_grad():
        end = time.time()
        for i, (images, target) in enumerate(val_loader):
            images = images.cuda()
            target = target.cuda()

            # compute output
            logits = model(images)
            loss = criterion(logits, target)

            # measure accuracy and record loss
            pred1, pred5 = accuracy(logits, target, topk=(1, 5))
            n = images.size(0)
            losses.update(loss.item(), n)
            top1.update(pred1[0], n)
            top5.update(pred5[0], n)

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            # if i % args.val_print_freq == 0:
            #     progress.display(i)
            
        # print(' * Acc@1 {top1.avg:.3f} Acc@5 {top5.avg:.3f}'
        #       .format(top1=top1, top5=top5))

    return losses.avg, top1.avg, top5.avg


if __name__ == '__main__':
  main()
