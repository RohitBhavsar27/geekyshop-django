from django.shortcuts import redirect, render

from cart.models import Cart, CartItem
from store.models import Product

# Create your views here.


def _cart_id(request):
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart

def add_cart(request, product_id):
    product = Product.objects.get(id = product_id)  # get the product
    try:
        cart = Cart.objects.get(cart_id = _cart_id(request))    # get the cart using the cart_id present in the session
    except Cart.DoesNotExist:
        cart = request.session.create(
            cart_id = _cart_id(request)
        )
    cart.save()
    
    try:
        cart_item = CartItem.objects.get(product=product, cart=cart)
        cart_item.quantity += 1
        cart_item.save()
    except cart_item.DoesNotExist:
        cart_item = CartItem.objects.create(
            product = product,
            quantity = 1,
            cart = cart,
        )
        cart_item.save()
    return redirect('cart')

def cart(request):
    return render(request, 'store/cart.html')