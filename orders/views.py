from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

import stripe
import datetime
import json

from cart.models import CartItem
from .forms import OrderForm
from .models import Order, Payment, OrderProduct
from store.models import Product
from django.contrib.auth.decorators import login_required

stripe.api_key = settings.STRIPE_SECRET_KEY


# @login_required(login_url="login")
def place_order(request, total=0, quantity=0):
    current_user = request.user
    cart_items = CartItem.objects.filter(user=current_user)

    if cart_items.count() <= 0:
        return redirect("store")

    grand_total = 0
    tax = 0

    for cart_item in cart_items:
        total += cart_item.product.price * cart_item.quantity
        quantity += cart_item.quantity

    tax = (2 * total) / 100
    grand_total = total + tax

    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data["first_name"]
            data.last_name = form.cleaned_data["last_name"]
            data.phone = form.cleaned_data["phone"]
            data.email = form.cleaned_data["email"]
            data.address_line_1 = form.cleaned_data["address_line_1"]
            data.address_line_2 = form.cleaned_data["address_line_2"]
            data.country = form.cleaned_data["country"]
            data.state = form.cleaned_data["state"]
            data.city = form.cleaned_data["city"]
            data.order_note = form.cleaned_data["order_note"]
            data.order_total = grand_total
            data.tax = tax
            data.ip = request.META.get("REMOTE_ADDR")
            data.save()

            #? Generate unique order number
            current_date = datetime.date.today().strftime("%Y%m%d")
            order_number = current_date + str(data.id)
            data.order_number = order_number
            data.save()

            order = Order.objects.get(
                user=current_user, is_ordered=False, order_number=order_number
            )
            context = {
                "order": order,
                "cart_items": cart_items,
                "total": total,
                "tax": tax,
                "grand_total": grand_total,
                "STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY,
            }
            return render(request, "orders/payments.html", context)

    return redirect("checkout")


@csrf_exempt
def create_checkout_session(request):
    if request.method == "POST":
        cart_items = CartItem.objects.filter(user=request.user)
        line_items = []

        for item in cart_items:
            line_items.append(
                {
                    "price_data": {
                        "currency": "usd",  # Using USD
                        "unit_amount": int(item.product.price * 100),  # in cents
                        "product_data": {
                            "name": item.product.product_name,
                        },
                    },
                    "quantity": item.quantity,
                }
            )

        latest_order = Order.objects.filter(user=request.user, is_ordered=False).latest(
            "created_at"
        )

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=f"http://localhost:8000/orders/order_complete?order_number={latest_order.order_number}&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url="http://localhost:8000/cart/checkout/",
            metadata={
                "order_id": latest_order.id,
                "user_id": request.user.id,
            },
        )

        return JsonResponse({"id": session.id})


# @login_required(login_url="login")
def order_complete(request):
    order_number = request.GET.get("order_number")
    session_id = request.GET.get("session_id")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        payment_intent = stripe.PaymentIntent.retrieve(session.payment_intent)
        print(payment_intent)

        #? Store transaction details inside payment model 
        payment = Payment.objects.create(
            user=request.user,
            payment_id=payment_intent.id,
            payment_method="Stripe",
            amount_paid=payment_intent.amount_received
            / 100,  # convert cents to dollars
            status=payment_intent.status,
        )

        order = Order.objects.get(order_number=order_number, is_ordered=False)
        order.payment = payment
        order.is_ordered = True
        order.save()

        #? Move the cart items to order product table
        cart_items = CartItem.objects.filter(user=request.user)

        for item in cart_items:
            orderproduct = OrderProduct.objects.create(
                order=order,
                payment=payment,
                user=request.user,
                product=item.product,
                quantity=item.quantity,
                product_price=item.product.price,
                ordered=True,
            )
            orderproduct.variations.set(item.variations.all())
            orderproduct.save()

            #? Reduce the quantity of the sold product
            product = Product.objects.get(id=item.product.id)
            product.stock -= item.quantity
            product.save()
            
        #? Clear cart once purchase is completed
        CartItem.objects.filter(user=request.user).delete()

        #? Send email
        mail_subject = "Thank you for your order!"
        message = render_to_string(
            "orders/order_recieved_email.html",
            {
                "user": request.user,
                "order": order,
            },
        )
        to_email = request.user.email
        send_email = EmailMessage(mail_subject, message, to=[to_email])
        send_email.send()

        ordered_products = OrderProduct.objects.filter(order_id=order.id)
        subtotal = sum(item.product_price * item.quantity for item in ordered_products)

        context = {
            "order": order,
            "ordered_products": ordered_products,
            "order_number": order.order_number,
            "transID": payment.payment_id,
            "payment": payment,
            "subtotal": subtotal,
        }
        return render(request, "orders/order_complete.html", context)

    except (stripe.error.StripeError, Order.DoesNotExist):
        return redirect("home")
